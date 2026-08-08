#!/usr/bin/env bash
# Build the linux/amd64 Octave model image for pyLeman2000.
#
# For publishing to GHCR, use .github/workflows/docker-publish.yml.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE_TAG="${1:-pyleman2000-octave:dev}"

echo "Building ${IMAGE_TAG} from repository root (linux/amd64) ..."
docker build \
  --platform=linux/amd64 \
  -f "${ROOT}/docker/octave/Dockerfile" \
  -t "${IMAGE_TAG}" \
  "${ROOT}"

echo "Done. Local override example:"
echo "  leman2000(..., docker_image='${IMAGE_TAG}')"
echo "Default installs pull ghcr.io/cms-cambridge/pyleman2000-octave (see README)."
echo
echo "For the compiled MATLAB worker (requires MATLAB Compiler on Linux), see:"
echo "  ./scripts/build_matlab_image.sh"
echo "  docker/matlab/README.md"
