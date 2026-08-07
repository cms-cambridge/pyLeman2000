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

## Caveats

- 4-core VM with 15 GB RAM; a 24-thread workstation should show larger gains
  at higher worker counts.
- Docker used the `fuse-overlayfs` driver (the sandbox cannot create overlay
  whiteout device nodes). This inflates container setup somewhat, which biases
  slightly against multi-worker conditions.
- 2 repeats per condition, so treat small differences (under ~10%) as noise.
