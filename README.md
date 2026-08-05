# pyLeman2000

Python wrapper for Leman's (2000) tonal contextuality model.

The original model was published in a 2000 *Music Perception* paper, and was
shown to provide a psychoacoustic account of the Krumhansl-Kessler probe-tone
data (Leman, 2000). Leman and colleagues released this model as part of the
IPEM Toolbox, which now only runs on old MATLAB versions. This package wraps
the model in Docker (via the
[Docker SDK for Python](https://docker-py.readthedocs.io/)) for cross-platform
use.

Two backends are supported:

| Backend | Image | Notes |
|---------|-------|-------|
| **MATLAB MCR** (default) | pinned `ghcr.io/pmcharrison/leman_2000` | Bit-identical to archived R snapshots (`1e-12`) |
| **GNU Octave** | build locally from `docker/octave/` | License-free; correlations agree with MATLAB to ~`3e-6` on 44.1 kHz input |

This is a Python port of [`leman2000R`](https://github.com/pmcharrison/leman2000R).

## Requirements

- Python 3.10+
- [Docker](https://docs.docker.com/get-docker/) installed and running
  (`docker info` should succeed)
- On first use of the default backend, a reproducibly pinned
  `ghcr.io/pmcharrison/leman_2000` image is pulled (~1 GB compressed). That
  first pull can take several minutes; download and extraction progress is
  reported on standard error. Subsequent runs also report preparing / running /
  reading status (with an elapsed-time heartbeat while the model executes).
  Silence both with `leman2000(..., show_progress=False)`.

Input and output files are copied in and out of the container rather than
bind-mounted, so no Docker file sharing configuration is needed. Analyses work
regardless of where the audio lives, including paths that Docker Desktop does
not share by default (such as WAV files inside `site-packages`).

> **Note:** The underlying images target `linux/amd64`. On Apple Silicon, enable
> Docker Desktop's amd64/Rosetta or QEMU emulation, then verify with
> `docker run --platform=linux/amd64 --rm hello-world`. Emulated runs are
> slower than native amd64 hardware. Most of the per-call cost for the MATLAB
> backend is Runtime startup (several seconds even for short WAVs). For many
> analyses in one process, reuse a warm container with `Leman2000Session`
> (see below).

## Installation

```bash
python3 -m pip install git+https://github.com/cms-cambridge/pyLeman2000.git
```

For local development:

```bash
python3 -m pip install -e ".[dev]"
```

Optional: pre-pull the pinned MATLAB model image before your first analysis:

```bash
docker pull "$(python3 -c 'from pyleman2000.docker_runner import DEFAULT_IMAGE; print(DEFAULT_IMAGE)')"
```

### Octave backend (license-free)

Build the Octave image from this repository (pins
[cms-cambridge/IPEMToolbox](https://github.com/cms-cambridge/IPEMToolbox) at the
commit in `docker/octave/Dockerfile`):

```bash
./scripts/build_octave_image.sh
```

Then pass the image to the API:

```python
from pyleman2000 import DEFAULT_OCTAVE_IMAGE, example_wav_path, leman2000

result = leman2000(
    input_file=example_wav_path(),
    local_decay_sec=[0.1, 0.2],
    global_decay_sec=[1.0, 2.0],
    docker_image=DEFAULT_OCTAVE_IMAGE,
)
```

Octave uses a MATLAB-compatible `resample` shim inside the toolbox fork. On
44.1 kHz input, running correlations typically match the MATLAB backend to
about `3e-6` (not `1e-12`). Feed 22.05 kHz audio if you need near-exact
cross-backend agreement.
## Choosing parameters

There is not much clarity in the literature on which local/global decay
parameters are best. Previous work has therefore grid-searched many
combinations, which is what this package facilitates: pass sequences for
`local_decay_sec` and `global_decay_sec` to obtain all pairwise results. See
Bigand et al. (2014) for an example of using Leman's model across parameter
settings when relating auditory short-term memory accounts to musical syntax
findings.

`local_global_comparison` gives the running correlation between local and
global tonal images over time. Higher values mean the short-term (local) and
longer-term (global) representations are more similar at that moment. Optional
`windows` summarise those correlations over closed time intervals of interest
(for example chord or phrase spans). This differs from `leman2000R`, which uses
half-open intervals `[start, end)`: pyLeman2000 includes both endpoints, so a
sample that falls exactly on a shared boundary contributes to both adjacent
windows.

Input files must use a `.wav` extension. The Dockerised binary inherits the
IPEM/MATLAB WAV constraints of the original toolbox; if a file fails inside
the container, try a standard PCM WAV (for example mono or stereo, 16-bit,
44.1 kHz).

## Example

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

### Repeated analyses (warm container)

Each one-shot `leman2000(...)` call starts a fresh container and pays MATLAB
Runtime startup again. When analysing many files, keep one container alive:

```python
from pyleman2000 import Leman2000Session, example_wav_path

with Leman2000Session() as session:
    first = session.run(
        input_file=example_wav_path(),
        local_decay_sec=0.1,
        global_decay_sec=1.0,
    )
    second = session.run(
        input_file=example_wav_path(),
        local_decay_sec=[0.1, 0.5],
        global_decay_sec=[1.0, 2.0],
    )
```

The Runtime still starts on every `run`, but later calls in the same session
are typically faster (filesystem caches stay warm), especially on Apple Silicon.

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

```python
result.windowed_local_global_comparison
```

```text
   local_decay_sec  global_decay_sec  window_id  window_start  window_end  local_global_correlation
0              0.1               1.0          1           0.0         0.1                  0.999977
1              0.5               1.0          1           0.0         0.1                  1.000000
2              0.1               2.0          1           0.0         0.1                  0.999974
3              0.5               2.0          1           0.0         0.1                  0.999999
4              0.1               1.0          2           0.1         0.2                  0.998674
5              0.5               1.0          2           0.1         0.2                  0.999988
6              0.1               2.0          2           0.1         0.2                  0.998546
7              0.5               2.0          2           0.1         0.2                  0.999972
```

Window intervals include both endpoints. A timestamp on a boundary shared by
adjacent windows contributes to both windows. This is an intentional divergence
from `leman2000R`, which uses half-open `[start, end)`. `window_id` is 1-based,
and windowed rows are ordered window-major (all parameter combinations for
window 1, then window 2, and so on).

`leman2000` returns a `Leman2000Result` dataclass with:

- `audio_length_sec`, `num_channels`, `sample_rate`
- `local_global_comparison` — pandas DataFrame of running local/global correlations
- `windowed_local_global_comparison` — optional windowed averages
- `auditory_nerve` / `periodicity_pitch` — optional heavy intermediate outputs
  (nested dictionaries from the MATLAB binary; omit unless you need them)

The result object itself is frozen (attribute reassignment is blocked), but
embedded DataFrames remain mutable through pandas APIs. Constructor inputs are
copied so later edits to caller-owned objects do not alter the result. Result
equality is identity-based; compare DataFrames or fields explicitly when needed.

## Tests

Unit tests do not require Docker:

```bash
python3 -m pip install -e ".[dev]"
python3 -m pytest -v -m "not integration"
```

Integration and R-snapshot tests require Docker:

```bash
docker pull "$(python3 -c 'from pyleman2000.docker_runner import DEFAULT_IMAGE; print(DEFAULT_IMAGE)')"
python3 -m pytest -v -m integration
```

Snapshot CSVs under `tests/snapshots/` were generated from
[`leman2000R`](https://github.com/pmcharrison/leman2000R) via
`scripts/generate_r_snapshots.R`.

## References

Bigand, E., Delbé, C., Poulin-Charronnat, B., Leman, M., & Tillmann, B. (2014).
Empirical evidence for musical syntax processing? Computer simulations reveal
the contribution of auditory short-term memory.
*Frontiers in Systems Neuroscience, 8*, 94.
https://doi.org/10.3389/fnsys.2014.00094

Leman, M. (2000). An auditory model of the role of short-term memory in probe-tone
ratings. *Music Perception, 17*(4), 481–509.
