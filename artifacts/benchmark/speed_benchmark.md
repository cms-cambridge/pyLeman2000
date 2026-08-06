# pyLeman2000 vs leman2000R speed benchmark

Collected: `2026-08-06T07:26:58.232527+00:00`

## Setup

- Host: `Linux-6.12.94+-x86_64-with-glibc2.39`
- Docker storage driver: `vfs` (absolute times inflated vs overlayfs; relative comparison still valid)
- Python: `3.12.3`, pyLeman2000 `0.1.0`
- R: `4.6.1`, leman2000R `0.1.0` (`6067bfdfad2a`)
- Python image: `ghcr.io/cms-cambridge/pyleman2000-octave:dev`
- R image: `ghcr.io/pmcharrison/leman_2000:latest`
- Parameters: local=[0.1, 0.5], global=[1.0, 2.0], repeats=3, warmup=1

Audio:
- short: packaged `hihat.wav` (0.371s)
- 5s: tiled hihat (5.0s)

Notes:
- Oneshot conditions are interleaved (R, Python default, Python detail5)
  within each repeat so Docker/OS cache effects are shared more evenly.
- `leman2000R` always requests model `detail=5`.
- pyLeman2000 default uses `detail=0` unless intermediate outputs are kept.
- `oneshot_detail5` sets `keep_periodicity_pitch=True` so Python also uses detail=5.
- `session_default` reuses one warm Docker container via `Leman2000Session`.

## Results (wall clock, seconds)

| Audio | Implementation | Mode | Mean | Median | Min | Max |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| short | leman2000R | `oneshot_default` | 22.921 | 23.062 | 22.585 | 23.115 |
| short | pyLeman2000 | `oneshot_default` | 14.670 | 14.721 | 14.271 | 15.018 |
| short | pyLeman2000 | `oneshot_detail5` | 14.433 | 14.226 | 14.197 | 14.875 |
| short | pyLeman2000 | `session_default` | 1.587 | 1.592 | 1.576 | 1.593 |
| 5s | leman2000R | `oneshot_default` | 27.221 | 27.756 | 25.492 | 28.416 |
| 5s | pyLeman2000 | `oneshot_default` | 33.992 | 34.101 | 33.470 | 34.405 |
| 5s | pyLeman2000 | `oneshot_detail5` | 34.774 | 34.987 | 33.874 | 35.462 |
| 5s | pyLeman2000 | `session_default` | 20.056 | 20.109 | 19.738 | 20.322 |

## Relative speed (mean)

### short

- `oneshot_default`: Python **1.56× faster** than R (R 22.921s vs Python 14.670s)
- `oneshot_detail5`: Python **1.59× faster** than R (R 22.921s vs Python 14.433s)
- `session_default`: Python **14.44× faster** than R (R 22.921s vs Python 1.587s)

### 5s

- `oneshot_default`: Python **1.25× slower** than R (R 27.221s vs Python 33.992s)
- `oneshot_detail5`: Python **1.28× slower** than R (R 27.221s vs Python 34.774s)
- `session_default`: Python **1.36× faster** than R (R 27.221s vs Python 20.056s)

