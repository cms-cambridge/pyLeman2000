"""Helpers for Docker-backed tests."""

from __future__ import annotations


def docker_daemon_available() -> bool:
    """Return True when the Docker daemon responds to ping."""
    try:
        import docker
        from docker.errors import DockerException

        client = docker.from_env()
        try:
            client.ping()
            return True
        except DockerException:
            return False
        finally:
            client.close()
    except Exception:
        return False
