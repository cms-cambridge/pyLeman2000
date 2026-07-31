# pyLeman2000

Python wrapper for Leman's (2000) tonal contextuality model.

The original model was published in a 2000 Music Perception paper, and was shown
to provide a psychoacoustic account of the Krumhansl-Kessler probe-tone data.
Leman and colleagues released this model as part of the IPEM Toolbox, which now
only runs on old MATLAB versions. This package wraps the compiled implementation
in Docker (via the [Docker SDK for Python](https://docker-py.readthedocs.io/))
for cross-platform use.

This is a Python port of [`leman2000R`](https://github.com/pmcharrison/leman2000R).

## Requirements

- Python 3.10+
- [Docker](https://docker.io/) installed and running
- On first use, the image `ghcr.io/pmcharrison/leman_2000:latest` will be pulled

> **Note:** The underlying image targets linux/amd64 (Intel/AMD). It may not work
> on Apple Silicon without emulation.

## Installation

```bash
pip install git+https://github.com/pmcharrison/pyLeman2000.git
```

For local development:

```bash
pip install -e ".[dev]"
```

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
1              0.1               1.0          2           0.1         0.2                  0.998674
2              0.1               2.0          1           0.0         0.1                  0.999974
3              0.1               2.0          2           0.1         0.2                  0.998546
4              0.5               1.0          1           0.0         0.1                  1.000000
5              0.5               1.0          2           0.1         0.2                  0.999988
6              0.5               2.0          1           0.0         0.1                  0.999999
7              0.5               2.0          2           0.1         0.2                  0.999972
```

`leman2000` returns a `Leman2000Result` dataclass with:

- `audio_length_sec`, `num_channels`, `sample_rate`
- `local_global_comparison` — pandas DataFrame of running local/global correlations
- `windowed_local_global_comparison` — optional windowed averages
- `auditory_nerve` / `periodicity_pitch` — optional heavy intermediate outputs

## Tests

```bash
pytest
```

Docker-backed integration tests are marked and skipped when Docker is unavailable:

```bash
pytest -m integration
```
