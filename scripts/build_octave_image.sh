#!/usr/bin/env bash
# Build the Octave model image for pyLeman2000 (native host architecture).
#
# For multi-arch publish to GHCR, use .github/workflows/docker-publish.yml.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE_TAG="${1:-pyleman2000-octave:dev}"

echo "Building ${IMAGE_TAG} from ${ROOT}/docker/octave (native platform) ..."
docker build \
  -f "${ROOT}/docker/octave/Dockerfile" \
  -t "${IMAGE_TAG}" \
  "${ROOT}/docker/octave"

echo "Done. Local override example:"
echo "  leman2000(..., docker_image='${IMAGE_TAG}')"
echo "Default installs pull ghcr.io/cms-cambridge/pyleman2000-octave (see README)."
