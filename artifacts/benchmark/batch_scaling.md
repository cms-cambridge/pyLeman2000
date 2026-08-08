# leman2000_batch worker scaling

Collected: `2026-08-07T18:08:07.337577+00:00`

- Backend: matlab (`ghcr.io/cms-cambridge/pyleman2000-matlab@sha256:3efee1cb706a3b7239c0d852e49ab2b0af5d837c72af53a0e3a4bb88fdbf9782`)
- Host: `Linux-6.12.94+-x86_64-with-glibc2.39`
- Params: local=[0.1, 0.5], global=[1.0, 2.0], repeats=2 (after 1 warmup)

Wall time includes pool startup. `speedup` is mean time at `workers=1` divided by mean time at that worker count.

| Duration | Files | Workers | Mean (s) | Throughput (files/s) | Speedup vs 1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 5s | 4 | 1 | 13.93 | 0.287 | 1.00x |
| 5s | 4 | 2 | 13.44 | 0.298 | 1.04x |
| 5s | 4 | 4 | 22.10 | 0.181 | 0.63x |
| 5s | 8 | 1 | 22.99 | 0.348 | 1.00x |
| 5s | 8 | 2 | 17.96 | 0.445 | 1.28x |
| 5s | 8 | 4 | 26.40 | 0.303 | 0.87x |
| 30s | 4 | 1 | 56.34 | 0.071 | 1.00x |
| 30s | 4 | 2 | 34.60 | 0.116 | 1.63x |
| 30s | 4 | 4 | 33.79 | 0.118 | 1.67x |
| 30s | 8 | 1 | 101.93 | 0.078 | 1.00x |
| 30s | 8 | 2 | 58.50 | 0.137 | 1.74x |
| 30s | 8 | 4 | 49.44 | 0.162 | 2.06x |

Reference timings on the same host: worker startup (Runtime load plus
`IPEMSetup`) 4.63 s; one warm analysis 3.39 s for 5 s audio and 13.67 s for
30 s audio.

## What this says

- The deciding ratio is per-file compute against the ~4.6 s worker startup,
  not file count. At 5 s audio a file costs less to analyse (3.4 s) than a
  worker costs to start, so extra workers lose; at 30 s audio a file costs
  13.7 s and extra workers win.
- Short audio never pays off here. `workers=4` on 5 s audio is *slower* than
  sequential (0.63x at 4 files, 0.87x at 8), because four Runtime startups and
  CPU contention outweigh the overlap.
- Long audio pays off clearly: 1.63–2.06x, improving with file count as the
  fixed startup is amortised over more work.
- Speedup is sublinear (2.06x on 4 cores at best) because the compiled MATLAB
  worker is already multithreaded, so workers contend for the same cores.

## Cost scales with audio length, not grid size

Extra decay combinations are nearly free, because `IPEMCalcANI` and
`IPEMPeriodicityPitch` run once per file while only `IPEMContextualityIndex`
repeats per combination. Warm-run times on the same host:

| Audio | 1 combo | 4 combos | 16 combos | 36 combos |
| --- | ---: | ---: | ---: | ---: |
| 5 s | 2.15 s | 2.12 s | 2.20 s | 2.44 s |
| 30 s | 12.22 s | 12.53 s | 13.48 s | 14.79 s |

A 36x larger grid costs 13% (5 s) to 21% (30 s). Compute and memory instead
track audio length, both close to linear:

| Audio | Compute | Peak worker memory (PSS) |
| --- | ---: | ---: |
| 30 s | 13.7 s | 900 MB |
| 60 s | 26.0 s | 1.1 GB |
| 120 s | 51.5 s | 1.8 GB |

That is roughly 0.43 s of compute and 10 MB of memory per audio-second, on a
625 MB idle baseline. Worker sizing therefore keys off total audio duration,
and the per-worker RAM budget grows with the longest file.

## Auto-sizing validation

Re-running the same scenarios with the duration-based heuristic (no explicit
`workers=`), against the manual results above:

| Scenario | Chosen workers | Wall | vs `workers=1` | vs best manual |
| --- | ---: | ---: | ---: | ---: |
| 4 x 5 s | 1 | 14.91 s | 0.93x | 0.90x |
| 8 x 5 s | 2 | 19.77 s | 1.16x | 0.91x |
| 4 x 30 s | 4 | 35.69 s | 1.58x | 0.95x |
| 8 x 30 s | 4 | 51.68 s | 1.97x | 0.96x |

The heuristic never selects a losing configuration and lands within 4-10% of
the best hand-picked worker count (single repeat, so most of that gap is
run-to-run noise).

## Caveats

- 4-core VM with 15 GB RAM; a 24-thread workstation should show larger gains
  at higher worker counts.
- Docker used the `fuse-overlayfs` driver (the sandbox cannot create overlay
  whiteout device nodes). This inflates container setup somewhat, which biases
  slightly against multi-worker conditions.
- 2 repeats per condition, so treat small differences (under ~10%) as noise.
