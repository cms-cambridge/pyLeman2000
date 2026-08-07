# Old MATLAB image vs new compiled MATLAB worker

Collected: 2026-08-06 on `musix.mus.cam.ac.uk` (same machine, overlay2).

## Images

| Role | Image | On-disk size | Notes |
| --- | --- | ---: | --- |
| Old | `ghcr.io/pmcharrison/leman_2000:latest` | 2.8 GB | Digest `sha256:08d5ce84…2442` (former pyLeman2000 `DEFAULT_IMAGE`). MCR **v84** (R2014b-era). CLI entrypoint `/leman_2000_docker.sh`. |
| New | `pyleman2000-matlab-worker:latest` | 3.8 GB | R2026a custom Runtime + persistent file-queue worker. |

Parameters: local=`0.1,0.2`, global=`1.0,2.0` (4 combos), `detail=0`, 3 repeats after warmup.

Modes:

- **oneshot** — full container lifecycle per analysis (old: `docker run`; new: start worker → one request → stop)
- **warm** — container already up (old: `docker exec` of the compiled binary, which still reloads MCR each time; new: one request to the already-loaded worker process)

## Results (wall clock, seconds, mean of 3)

| Audio | Backend | Mode | Mean | Median | Min | Max |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| 0.37 s | Old MATLAB | oneshot | 11.20 | 11.18 | 11.12 | 11.28 |
| 0.37 s | New MATLAB | oneshot | 4.57 | 4.56 | 4.56 | 4.58 |
| 0.37 s | Old MATLAB | warm | 7.10 | 7.11 | 7.09 | 7.11 |
| 0.37 s | New MATLAB | warm | 0.57 | 0.31 | 0.27 | 1.13 |
| 5 s | Old MATLAB | oneshot | 14.91 | 14.91 | 14.78 | 15.03 |
| 5 s | New MATLAB | oneshot | 6.25 | 6.26 | 6.18 | 6.32 |
| 5 s | Old MATLAB | warm | 10.67 | 10.65 | 10.57 | 10.78 |
| 5 s | New MATLAB | warm | 2.05 | 2.03 | 2.00 | 2.10 |

New worker process startup (paid once): **2.84 s**.

## Takeaways

- **New is faster in every condition.** Oneshot ~2.4× (5 s: 14.9 → 6.3 s); warm ~5× (5 s: 10.7 → 2.0 s).
- The old image’s “warm” path still reloads the compiled app / MCR on every `docker exec`, so most of its cost remains fixed overhead. The new worker keeps Runtime + `IPEMSetup` resident.
- Isolating extra compute for the additional ~4.6 s of audio (warm long − warm short): old ≈ 3.6 s, new ≈ 1.5 s — newer MATLAB/numerics help too, but the big win is the persistent process.
- Image size: old is smaller on disk (2.8 vs 3.8 GB) because it ships an older, thinner MCR; the new image trades ~1 GB for R2026a + a real persistent worker.
