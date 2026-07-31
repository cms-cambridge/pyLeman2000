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
from pyleman2000 import leman2000
from pyleman2000.api import example_wav_path

result = leman2000(
    input_file=example_wav_path(),
    local_decay_sec=[0.1, 0.5],
    global_decay_sec=[1.0, 2.0],
    windows=[(0.0, 0.1), (0.1, 0.2)],
)

print(result.local_global_comparison.head())
print(result.windowed_local_global_comparison)
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
