# Compiled MATLAB R2026a spike vs Octave backend

Collected: 2026-08-06, same machine for both backends.

## Setup

- Host: `musix.mus.cam.ac.uk`, AMD Ryzen 9 5900X (24 threads), Docker 29.4.2 (`overlay2`)
- MATLAB R2026a, compiled with MATLAB Compiler (`mcc -m`), run against the
  MATLAB Runtime with `MLM_LICENSE_FILE` pointing at a nonexistent file to
  confirm the compiled app needs no licence
- IPEM Toolbox: `cms-cambridge/IPEMToolbox` master plus a local one-line patch
  skipping `path2rc` when `isdeployed` (`savepath` does not exist in the Runtime)
- Octave backend: `ghcr.io/cms-cambridge/pyleman2000-octave:dev`
- Parameters for every condition: local=[0.1, 0.2], global=[1.0, 2.0] (4 combos),
  `detail=0`, 3 repeats
- Audio: packaged `hihat.wav` (0.371 s) and the same file tiled to 5 s

Modes:

- `oneshot` starts a fresh process per analysis (Octave: `docker run`;
  MATLAB: a fresh compiled-app invocation, no container)
- `warm` reuses an already-started process (Octave: `docker exec` into a
  long-lived container, as `Leman2000Session` does; MATLAB: one request to the
  persistent compiled worker)

## Results (wall clock, seconds, mean of 3)

| Audio | Backend | Mode | Mean | Median | Min | Max |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| 0.37 s | Octave | `oneshot` | 2.307 | 2.064 | 2.064 | 2.794 |
| 0.37 s | Octave | `warm` | 1.726 | 1.702 | 1.699 | 1.777 |
| 0.37 s | MATLAB compiled | `oneshot` | 4.488 | 4.077 | 4.038 | 5.348 |
| 0.37 s | MATLAB compiled | `warm` | 0.635 | 0.327 | 0.296 | 1.282 |
| 5 s | Octave | `oneshot` | 19.536 | 19.421 | 19.415 | 19.773 |
| 5 s | Octave | `warm` | 18.948 | 18.882 | 18.835 | 19.127 |
| 5 s | MATLAB compiled | `oneshot` | 5.776 | 5.699 | 5.676 | 5.953 |
| 5 s | MATLAB compiled | `warm` | 1.859 | 1.856 | 1.792 | 1.931 |

MATLAB worker startup (Runtime load plus `IPEMSetup`, paid once): 5.69 s.

## What this says

- Compiled MATLAB is dramatically faster at the actual numerics, not just at
  startup. Subtracting the short-audio time from the 5 s time to isolate the
  extra compute: Octave spends about 17.2 s, MATLAB about 1.5 s, so roughly an
  11x difference in compute throughput.
- A persistent process is worth much more for MATLAB than for Octave. The
  Runtime costs about 3.8 s of fixed startup per one-shot invocation, so
  MATLAB one-shot is actually *slower* than Octave one-shot on 0.37 s audio
  (4.49 s vs 2.31 s) while being 3.4x faster on 5 s audio.
- Combining both wins, the persistent compiled MATLAB worker runs 5 s audio in
  1.86 s against 18.95 s for a warm Octave container, about 10x faster.
- Reusing the Octave container barely helps (19.54 s to 18.95 s at 5 s),
  because Octave's cost is compute, not startup.

## Correctness

Outputs from both the compiled one-shot app and the worker were compared with
the R snapshots in `tests/snapshots/r_hihat_local_global_comparison.csv` across
all four decay combinations: maximum absolute difference 2.7e-6, inside the 1e-5
tolerance the snapshot tests already use for the Octave backend.

## Fixes needed to get here

- `IPEMContextualityIndex.m` used the removed `[ws,wf] = warning` form
  (merged upstream in cms-cambridge/IPEMToolbox#2).
- `IPEMSetup.m` calls `path2rc`, which calls `savepath`, which does not exist in
  the Runtime. Guarded with `~isdeployed`.
- `wavread`/`wavwrite` are gone in R2026a, so the fork's `OctaveCompat` shims
  have to be on the path for MATLAB too.
- Standalone apps receive all arguments as text, so `detail > 1` was silently
  true for `detail='0'` (char 48). The spike now parses numeric arguments
  explicitly; without this, `detail=0` requests returned the full auditory
  nerve and periodicity pitch data (1.5 MB rather than 2.4 kB of JSON).

## Docker packaging and Runtime size

Built on the same machine after the timing spike.

| Image | On-disk size |
| --- | ---: |
| Official Runtime, no GPU (`containers.mathworks.com/matlab-runtime:r2026a`) | 7.74 GB |
| Custom Runtime for this worker only (`pyleman2000-matlab-runtime:custom`) | 3.8 GB |
| Packaged worker (`pyleman2000-matlab-worker`) | 3.8 GB |
| Octave backend (`pyleman2000-octave:dev`) | 4.41 GB |

The custom Runtime was produced with `compiler.runtime.createDockerImage` from
the worker's `buildresult.json` and `OptionalDependencies=none`. It installs
only Base + Standard/Graphics/Extended addons + Signal Processing + DSP.

The worker image was then packaged with `compiler.package.docker` against that
custom Runtime. Smoke test (license-free via a bogus `MLM_LICENSE_FILE`):

- container ready (Runtime load + `IPEMSetup`) in ~4 s
- one hihat request completed in ~1.3 s and wrote a valid JSON result
