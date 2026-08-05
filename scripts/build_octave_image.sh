#!/usr/bin/env bash
# Build the license-free Octave backend image for pyLeman2000.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE_TAG="${1:-pyleman2000-octave:dev}"

echo "Building ${IMAGE_TAG} from ${ROOT}/docker/octave ..."
docker build \
  --platform=linux/amd64 \
  -f "${ROOT}/docker/octave/Dockerfile" \
  -t "${IMAGE_TAG}" \
  "${ROOT}/docker/octave"

echo "Done. Use with:"
echo "  leman2000(..., docker_image='${IMAGE_TAG}')"
