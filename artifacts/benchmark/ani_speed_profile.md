# ANI batch vs spool speed

Collected: `2026-08-08T16:36:24.967068+00:00`

- Host: `pmch2@musix.mus.cam.ac.uk`
- ChunkLen: `1024`
- Repeats: `1`

| Audio | Batch ANI | Spool+read ANI | ANI × | Batch ANI+PP | Spool→PP | ANI+PP × |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 5.0 s | 1.366 s | 1.055 s | 1.30× | 2.155 s | 1.826 s | 1.18× |
| 30.0 s | 6.404 s | 5.661 s | 1.13× | 10.067 s | 9.963 s | 1.01× |

## Notes

- Speedup > 1 means spool path is faster.
- Spool path was built for memory, not wall-clock; expect similar or slower.
