# Batch vs sequential

Collected: `2026-08-07T16:42:16.567319+00:00`

- Host: `macOS-15.4.1-arm64-arm-64bit-Mach-O`
- pyLeman2000 `0.1.0`
- Files: 6, workers: 3 (auto would choose 4)
- Params: local=[0.1, 0.2], global=[1.0, 2.0], repeats=2

## Mean wall clock (seconds)

| Mode | Mean | Median | Min | Max |
| --- | ---: | ---: | ---: | ---: |
| oneshot sequential | 61.339 | 61.339 | 54.761 | 67.918 |
| session sequential | 12.083 | 12.083 | 11.701 | 12.465 |
| batch parallel (workers=3) | 24.476 | 24.476 | 24.461 | 24.492 |

## Relative speed (mean)

- batch vs session: **0.49×**
- batch vs oneshot: **2.51×**
