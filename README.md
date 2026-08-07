# pyLeman2000

Python wrapper for Leman's (2000) tonal contextuality model.

The model was published in *Music Perception* and accounts for the
Krumhansl–Kessler probe-tone data (Leman, 2000). This package runs it in
Docker: by default a compiled MATLAB Runtime worker, with an optional
license-free GNU Octave backend. It is a Python port of
[`leman2000R`](https://github.com/pmcharrison/leman2000R).

## Requirements

- Python 3.10+
- [Docker](https://docs.docker.com/get-docker/) installed and running
  (`docker info` should succeed)

The default image is pulled automatically on first use.

## Installation

```bash
python3 -m pip install pyLeman2000
```

## Quick start

```python
from pyleman2000 import example_wav_path, leman2000

result = leman2000(
    input_file=example_wav_path(),
    local_decay_sec=[0.1, 0.5],
    global_decay_sec=[1.0, 2.0],
    windows=[(0.0, 0.1), (0.1, 0.2)],
)

result.audio_length_sec, result.num_channels, result.sample_rate
```

```text
(0.3707936508, 1, 44100.0)
```

```python
result.local_global_comparison.head()
```

```text
   local_decay_sec  global_decay_sec  time_sec  running_correlation
0              0.1               1.0  0.000000             1.000000
1              0.1               1.0  0.014832             0.999999
2              0.1               1.0  0.029663             0.999998
3              0.1               1.0  0.044495             0.999996
4              0.1               1.0  0.059327             0.999993
```

`leman2000` returns a `Leman2000Result` with:

- `audio_length_sec`, `num_channels`, `sample_rate`
- `local_global_comparison` — running local/global correlations over time
- `windowed_local_global_comparison` — optional windowed averages
- `auditory_nerve` / `periodicity_pitch` — optional heavy intermediates
  (omit unless you need them)

Input files must use a `.wav` extension (standard PCM WAV works best, for
example mono or stereo, 16-bit, 44.1 kHz).

## Choosing parameters

There is not much clarity in the literature on which local/global decay
parameters are best. Previous work has therefore grid-searched many
combinations: pass sequences for `local_decay_sec` and `global_decay_sec` to
obtain all pairwise results. See Bigand et al. (2014) for an example.

`local_global_comparison` is the running correlation between local and global
tonal images. Higher values mean the short-term and longer-term
representationsations are more similar at that moment. Optional `windows` summarise
those correlations over closed time intervals (for example chord or phrase
spans). Unlike `leman2000R`'s half-open `[start, end)`, both endpoints are
included here.

## Analysing many files

For many files, use `leman2000_batch`: it opens a worker pool, picks a
RAM-aware worker count (override with `workers=` or `PYLEMAN2000_WORKERS`),
shows progress, and returns stacked DataFrames:

```python
from pyleman2000 import example_wav_path, leman2000_batch

paths = [example_wav_path(), example_wav_path()]
batch = leman2000_batch(
    paths,
    local_decay_sec=0.1,
    global_decay_sec=1.0,
)

batch.files
batch.local_global_comparison.head()
```

`batch.results` still holds per-file `Leman2000Result` objects when you need
`keep_*` payloads.

## Octave backend

Pass `backend="octave"` for the license-free image:

```python
from pyleman2000 import example_wav_path, leman2000

result = leman2000(
    input_file=example_wav_path(),
    local_decay_sec=0.1,
    global_decay_sec=1.0,
    backend="octave",
)
```

## Developer notes

### Local development

```bash
python3 -m pip install -e ".[dev]"
```

From a specific Git tag:

```bash
python3 -m pip install git+https://github.com/cms-cambridge/pyLeman2000.git@v0.2.0
```

Optional pre-pull of the default MATLAB image:

```bash
docker pull "$(python3 -c 'from pyleman2000 import DEFAULT_MATLAB_IMAGE; print(DEFAULT_MATLAB_IMAGE)')"
```

### Platform and Docker details

The default image is
[`ghcr.io/cms-cambridge/pyleman2000-matlab`](https://github.com/cms-cambridge/pyLeman2000/pkgs/container/pyleman2000-matlab)
(`linux/amd64`), digest-pinned as `DEFAULT_MATLAB_IMAGE`. Pass
`backend="octave"` for the Octave image built from `docker/octave/` against a
pinned [cms-cambridge/IPEMToolbox](https://github.com/cms-cambridge/IPEMToolbox)
commit.

Input and output files are copied in and out of the container rather than
bind-mounted, so no Docker file-sharing configuration is needed.

On Apple Silicon, enable Docker Desktop's amd64/Rosetta or QEMU emulation,
then verify with `docker run --platform=linux/amd64 --rm hello-world`.
Emulated runs are slower than native amd64. On 44.1 kHz input, running
correlations typically agree with archived MATLAB/R snapshots to about
`3e-6` (not bit-identical); feed 22.05 kHz audio for closer
cross-implementation agreement.

Silence pull/run progress with `show_progress=False`.

### Building images locally

Octave:

```bash
./scripts/build_octave_image.sh
# then: leman2000(..., backend="octave", docker_image="pyleman2000-octave:dev")
```

MATLAB (needs MATLAB Compiler on Linux amd64):

```bash
./scripts/build_matlab_image.sh                 # local pyleman2000-matlab:dev
./scripts/build_matlab_image.sh --tag 0.1.0 --push
```

Local `pyleman2000-octave:*` / `pyleman2000-matlab:*` tags are never pulled
from a registry; if missing you get an error pointing at the build script.

Octave publishing to GHCR is handled by `.github/workflows/docker-publish.yml`
(`linux/amd64`). Pushes to `main` refresh `:dev`; manual workflow dispatch
publishes version tags such as `:0.1.0` (and `:latest`). Package defaults are
digest pins of the 0.1.0 images. See `docker/matlab/README.md` for the MATLAB
worker protocol.

### Tests

Unit tests do not require Docker:

```bash
python3 -m pytest -v -m "not integration and not matlab"
```

Octave integration tests:

```bash
docker pull "$(python3 -c 'from pyleman2000 import DEFAULT_IMAGE; print(DEFAULT_IMAGE)')"
# or: ./scripts/build_octave_image.sh && use docker_image='pyleman2000-octave:dev'
python3 -m pytest -v -m integration
```

Compiled MATLAB smoke tests (no Compiler needed to run them):

```bash
docker pull "$(python3 -c 'from pyleman2000 import DEFAULT_MATLAB_IMAGE; print(DEFAULT_MATLAB_IMAGE)')"
python3 -m pytest -v -m matlab
```

Snapshot CSVs under `tests/snapshots/` were generated from
[`leman2000R`](https://github.com/pmcharrison/leman2000R) via
`scripts/generate_r_snapshots.R` (MATLAB backend). CI compares against those
archives with a looser tolerance (~`1e-5`).

### Result object notes

`Leman2000Result` is frozen (attribute reassignment is blocked), but embedded
DataFrames remain mutable through pandas APIs. Constructor inputs are copied
so later edits to caller-owned objects do not alter the result. Equality is
identity-based; compare DataFrames or fields explicitly when needed.
`window_id` is 1-based, and windowed rows are ordered window-major.

## References

Bigand, E., Delbé, C., Poulin-Charronnat, B., Leman, M., & Tillmann, B. (2014).
Empirical evidence for musical syntax processing? Computer simulations reveal
the contribution of auditory short-term memory.
*Frontiers in Systems Neuroscience, 8*, 94.
https://doi.org/10.3389/fnsys.2014.00094

Leman, M. (2000). An auditory model of the role of short-term memory in probe-tone
ratings. *Music Perception, 17*(4), 481–509.
