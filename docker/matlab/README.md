# Reproducibility notes for the compiled MATLAB backend

The Octave image is fully rebuildable in public CI. The MATLAB worker is not:
it needs MATLAB Compiler on a machine you control. Reproducibility for MATLAB
therefore means **pinned inputs + a scripted build + published image digests**,
not “anyone can `docker build` from scratch on GitHub-hosted runners.”

## What is pinned

| Input | Where |
| --- | --- |
| IPEMToolbox commit | `IPEM_REF` in `scripts/build_matlab_image.sh` (includes PR #2 warning fix and PR #3 `isdeployed` / `path2rc` guard) |
| MATLAB sources | `docker/matlab/*.m` |
| Runtime product set | `buildresult.json` produced by `mcc` (copied to `build/matlab/` on each build) |
| Image name | `ghcr.io/cms-cambridge/pyleman2000-matlab:<tag>` |
| Package default | Digest pin in `DEFAULT_MATLAB_IMAGE` (0.1.0 release) |

Current IPEM pin: `da1ca9d51d0096b3621a3ef8424622e30c32d9f6` (master after #3).

## Build host requirements

- Linux amd64
- MATLAB R2026a+ with MATLAB Compiler (and Docker able to pull MathWorks runtime helper images)
- `docker`, `git`, `gcc`, `make`, `python3`

Apple Silicon / macOS cannot produce the linux/amd64 Runtime image in-tree; use a Linux host (e.g. musix).

If the host does not have MATLAB yet (remote desktop, installer, Compiler
quirks), see [HOST_SETUP.md](HOST_SETUP.md).

## One command

```bash
# On the Compiler host, from a checkout of this repository:
./scripts/build_matlab_image.sh

# Publish to GHCR (requires docker login to ghcr.io):
./scripts/build_matlab_image.sh --tag dev --push
./scripts/build_matlab_image.sh --tag 0.2.0 --push
```

The script:

1. Clones IPEMToolbox at the pinned SHA and checks for the `isdeployed` guard
2. Builds `IPEMProcessAuditoryModelSafe.mexa64` with `AuditoryModel/Matlab8_UNIX`
3. Compiles `leman_2000_worker` with `mcc` (`-a` packs the toolbox)
4. Builds a **custom** Runtime image via `compiler.runtime.createDockerImage`
   (`OptionalDependencies=none`) — ~3.8 GB on R2026a, vs ~7.7 GB for the
   official no-GPU Runtime image
5. Packages the worker with `compiler.package.docker`
6. Smoke-tests the queue protocol on packaged `hihat.wav` with a bogus
   `MLM_LICENSE_FILE` (confirms license-free Runtime use)
7. Writes `build/matlab/PROVENANCE.txt` (IPEM SHA, MATLAB version, image id)

## Using the image

```python
from pyleman2000 import Leman2000Session, example_wav_path

with Leman2000Session() as session:
    result = session.run(
        example_wav_path(),
        local_decay_sec=0.1,
        global_decay_sec=1.0,
    )
```

Default backend is **MATLAB** (`DEFAULT_MATLAB_IMAGE`, digest-pinned). The
published image is smoke-tested in CI (``pytest -m matlab``) against the
archived R snapshots. Pass `backend="octave"` for the Octave image, or
override either with `docker_image=` for a local build tag.

Environment variables the worker container expects:

- `AGREE_TO_MATLAB_RUNTIME_LICENSE=yes`
- `MLM_LICENSE_FILE` pointing at a nonexistent path is fine (and recommended
  in smoke tests) so a host network license cannot be consulted by mistake

## Worker protocol

Bind-mounts:

- `/work` — `ready`, `req-<id>.json`, `res-<id>.json`, `stop`
- `/data` — WAV inputs and JSON outputs referenced inside requests

See `src/pyleman2000/matlab_worker.py` and `leman_2000_worker.m`.

## Benchmarks (musix, 2026-08-06)

See `artifacts/benchmark/matlab_compiled_spike.md` and
`artifacts/benchmark/old_vs_new_matlab.md`. Headline: persistent new worker
~2 s for 5 s audio vs ~11 s warm old MCR v84 image and ~19 s warm Octave.

## What this script deliberately does not do

- Run on GitHub-hosted runners (no Compiler license)
- Replace Octave as the default backend
- Vendor the multi-GB Runtime into git
