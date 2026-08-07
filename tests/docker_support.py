"""Helpers for Docker-backed tests."""

from __future__ import annotations

from typing import Any


def docker_daemon_available() -> bool:
    """Return True when the Docker daemon responds to ping."""
    try:
        import docker
    except ImportError:
        return False
    from docker.errors import DockerException

    try:
        client = docker.from_env()
    except Exception:
        return False
    try:
        client.ping()
        return True
    except DockerException:
        return False
    finally:
        try:
            client.close()
        except Exception:
            pass


def image_size_bytes(image_attrs: dict[str, Any]) -> int:
    """Return the on-disk image size from ``docker image inspect`` attrs.

    Parameters
    ----------
    image_attrs :
        The ``attrs`` mapping from a Docker SDK image object (or an equivalent
        inspect payload).

    Returns
    -------
    int
        Size in bytes.

    Raises
    ------
    KeyError, TypeError, ValueError
        If ``Size`` is missing or not a non-negative integer.
    """
    size = image_attrs["Size"]
    size_int = int(size)
    if size_int < 0:
        raise ValueError(f"Image Size must be non-negative, got {size_int}")
    return size_int


def docker_image_size_bytes(image: str) -> int:
    """Return the on-disk size of a local Docker image.

    Parameters
    ----------
    image :
        Image reference (tag or digest). The image must already exist locally
        (CI pulls it before the size tests run).

    Returns
    -------
    int
        Size in bytes from ``docker image inspect``.
    """
    import docker

    client = docker.from_env()
    try:
        return image_size_bytes(client.images.get(image).attrs)
    finally:
        client.close()


def container_memory_usage_bytes(stats: dict[str, Any]) -> int:
    """Return approximate working-set memory from a Docker stats payload.

    Prefers usage minus reclaimable file cache when those fields exist
    (cgroup v1 ``cache`` or cgroup v2 ``inactive_file``), otherwise falls
    back to raw ``memory_stats.usage``.

    Parameters
    ----------
    stats :
        One decoded object from ``container.stats(stream=False)``.

    Returns
    -------
    int
        Estimated bytes of memory in active use.
    """
    memory = stats.get("memory_stats")
    if not isinstance(memory, dict):
        raise TypeError("stats['memory_stats'] must be a mapping")
    usage = int(memory["usage"])
    if usage < 0:
        raise ValueError(f"memory usage must be non-negative, got {usage}")

    detail = memory.get("stats")
    cache = 0
    if isinstance(detail, dict):
        for key in ("inactive_file", "cache"):
            if key in detail:
                try:
                    cache = max(0, int(detail[key]))
                    break
                except (TypeError, ValueError):
                    cache = 0
    return max(0, usage - cache)
