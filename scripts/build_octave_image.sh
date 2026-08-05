#!/usr/bin/env bash
# Build the license-free Octave model image for pyLeman2000.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE_TAG="${1:-pyleman2000-octave:dev}"

echo "Building ${IMAGE_TAG} from ${ROOT}/docker/octave ..."
docker build \
  --platform=linux/amd64 \
  -f "${ROOT}/docker/octave/Dockerfile" \
  -t "${IMAGE_TAG}" \
  "${ROOT}/docker/octave"

echo "Done. The package defaults to this image; run:"
echo "  python3 -c 'from pyleman2000 import leman2000, example_wav_path; print(leman2000(example_wav_path(), 0.1, 1.0))'"
