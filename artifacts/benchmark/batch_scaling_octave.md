# leman2000_batch worker scaling

Collected: `2026-08-08T09:09:17.951302+00:00`

- Backend: octave (`ghcr.io/cms-cambridge/pyleman2000-octave@sha256:5883205b24d085ad4c03b46735ac849105109138f4aec9213ee8d8f3c05b4575`)
- Host: `Linux-6.12.94+-x86_64-with-glibc2.39`
- Params: local=[0.1, 0.5], global=[1.0, 2.0], repeats=2 (after 1 warmup)

Wall time includes pool startup. `speedup` is mean time at `workers=1` divided by mean time at that worker count.

| Duration | Files | Workers | Mean (s) | Throughput (files/s) | Speedup vs 1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 0.4s | 4 | 1 | 7.09 | 0.564 | 1.00x |
| 0.4s | 4 | 2 | 4.02 | 0.994 | 1.76x |
| 0.4s | 4 | 4 | 2.84 | 1.407 | 2.50x |
| 5s | 4 | 1 | 82.47 | 0.049 | 1.00x |
| 5s | 4 | 2 | 44.28 | 0.090 | 1.86x |
| 5s | 4 | 4 | 22.24 | 0.180 | 3.71x |

## What this says

- Unlike MATLAB, Octave starts a fresh interpreter for every file even inside
  a warm container. Opening several containers adds little fixed cost, so
  parallelism pays off even for the 0.37 s packaged example (2.50x at four
  workers).
- At 5 s per file, four workers reach 3.71x on four cores—close to linear.
  The Octave auto-sizer should therefore parallelize short files aggressively,
  rather than applying MATLAB's ~25 audio-seconds-per-worker threshold.
- Memory is the limiting factor for long files. Process PSS peaked at 1.9 GB
  for 5 s audio and 11.6 GB for 30 s audio. The Octave RAM model uses a
  measured 256 MB base plus 400 MB per audio-second, with 1.25x headroom.
- On this 16 GB VM, that model allows four workers for 5 s files but only one
  for 30 s files, avoiding an otherwise likely OOM.

## Caveats

- 4-core VM with 15 GB available RAM; two repeats per condition.
- Docker used `fuse-overlayfs`, which can inflate container setup slightly.
- The memory measurements use PSS from `/proc`; Docker's cgroup working-set
  metric excludes file-backed mappings and therefore reports a lower number.
