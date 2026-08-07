"""Python wrapper for Leman's (2000) tonal contextuality model."""

from importlib.metadata import PackageNotFoundError, version

from pyleman2000.api import (
    Leman2000Pool,
    Leman2000Session,
    example_wav_path,
    leman2000,
)
from pyleman2000.docker_runner import DEFAULT_IMAGE, Leman2000DockerError
from pyleman2000.matlab_worker import DEFAULT_MATLAB_IMAGE
from pyleman2000.types import Leman2000Result

__all__ = [
    "DEFAULT_IMAGE",
    "DEFAULT_MATLAB_IMAGE",
    "example_wav_path",
    "leman2000",
    "Leman2000DockerError",
    "Leman2000Pool",
    "Leman2000Result",
    "Leman2000Session",
]

try:
    __version__ = version("pyLeman2000")
except PackageNotFoundError:
    __version__ = "0+unknown"
