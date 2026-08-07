#!/usr/bin/env bash
# Build the compiled MATLAB Runtime worker image for pyLeman2000.
#
# This encodes the musix spike process so it can be re-run on any Linux amd64
# host that has MATLAB Compiler + Docker. It is intentionally *not* a
# GitHub-hosted Actions job: MathWorks licensing requires a machine you control.
#
# Prerequisites
#   - Linux amd64
#   - MATLAB R2026a (or later) with MATLAB Compiler, on PATH or via MATLAB_ROOT
#   - Docker with permission to build/pull MathWorks runtime helper images
#   - git, gcc, make, python3
#
# Usage
#   ./scripts/build_matlab_image.sh
#   ./scripts/build_matlab_image.sh --push
#   MATLAB_ROOT=$HOME/MATLAB/R2026a ./scripts/build_matlab_image.sh --tag 0.2.0 --push
#
# Outputs (under ${BUILD_DIR:-$PWD/build/matlab})
#   ipem/                         pinned IPEMToolbox checkout + rebuilt mex
#   mcc-worker/                   mcc output (binary + buildresult.json)
#   docker-context/               generated Runtime + worker Docker contexts
#   smoke/                        hihat smoke-test artefacts
#
# Final local image tag defaults to pyleman2000-matlab:dev. With --push, also
# tags and pushes ghcr.io/cms-cambridge/pyleman2000-matlab:<tag>.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MATLAB_SRC="${ROOT}/docker/matlab"

# Pin includes IPEMToolbox PR #3 (skip path2rc when isdeployed).
IPEM_REPO="${IPEM_REPO:-https://github.com/cms-cambridge/IPEMToolbox.git}"
IPEM_REF="${IPEM_REF:-da1ca9d51d0096b3621a3ef8424622e30c32d9f6}"

IMAGE_LOCAL_NAME="${IMAGE_LOCAL_NAME:-pyleman2000-matlab}"
IMAGE_TAG="dev"
RUNTIME_IMAGE_NAME="${RUNTIME_IMAGE_NAME:-pyleman2000-matlab-runtime}"
GHCR_IMAGE="${GHCR_IMAGE:-ghcr.io/cms-cambridge/pyleman2000-matlab}"
PUSH=0
SKIP_SMOKE=0
BUILD_DIR="${BUILD_DIR:-${ROOT}/build/matlab}"

usage() {
  sed -n '2,30p' "$0" | sed 's/^# \?//'
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --push) PUSH=1; shift ;;
    --skip-smoke) SKIP_SMOKE=1; shift ;;
    --tag) IMAGE_TAG="${2:?}"; shift 2 ;;
    --build-dir) BUILD_DIR="${2:?}"; shift 2 ;;
    -h|--help) usage 0 ;;
    *) echo "Unknown argument: $1" >&2; usage 1 ;;
  esac
done

LOCAL_IMAGE="${IMAGE_LOCAL_NAME}:${IMAGE_TAG}"
RUNTIME_IMAGE="${RUNTIME_IMAGE_NAME}:${IMAGE_TAG}"
GHCR_TAG="${GHCR_IMAGE}:${IMAGE_TAG}"

log() { printf '==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

resolve_matlab_root() {
  if [[ -n "${MATLAB_ROOT:-}" ]]; then
    [[ -x "${MATLAB_ROOT}/bin/matlab" ]] || die "MATLAB_ROOT=${MATLAB_ROOT} has no bin/matlab"
    printf '%s\n' "${MATLAB_ROOT}"
    return
  fi
  if command -v matlab >/dev/null 2>&1; then
    # Prefer a real install tree over a stub on PATH.
    local bin
    bin="$(command -v matlab)"
    if [[ -x "$(dirname "$bin")/../bin/matlab" ]]; then
      cd "$(dirname "$bin")/.." && pwd
      return
    fi
  fi
  for candidate in \
      "${HOME}/MATLAB/R2026a" \
      /usr/local/MATLAB/R2026a \
      /opt/MATLAB/R2026a; do
    if [[ -x "${candidate}/bin/matlab" ]]; then
      printf '%s\n' "${candidate}"
      return
    fi
  done
  die "Could not find MATLAB. Set MATLAB_ROOT to an R2026a+ install with Compiler."
}

require_linux_amd64() {
  [[ "$(uname -s)" == "Linux" ]] || die "MATLAB image builds are Linux-only (found $(uname -s))"
  local arch
  arch="$(uname -m)"
  [[ "${arch}" == "x86_64" || "${arch}" == "amd64" ]] \
    || die "MATLAB image builds require amd64 (found ${arch})"
}

require_tools() {
  command -v docker >/dev/null || die "docker is required"
  command -v git >/dev/null || die "git is required"
  command -v gcc >/dev/null || die "gcc is required"
  command -v make >/dev/null || die "make is required"
  command -v python3 >/dev/null || die "python3 is required"
  docker info >/dev/null 2>&1 || die "docker daemon is not reachable (docker info failed)"
}

clone_ipem() {
  local dest="$1"
  if [[ -d "${dest}/.git" ]]; then
    log "Updating existing IPEM checkout at ${dest}"
    git -C "${dest}" fetch --depth=1 origin "${IPEM_REF}"
    git -C "${dest}" checkout --force "${IPEM_REF}"
  else
    log "Cloning IPEMToolbox @ ${IPEM_REF}"
    rm -rf "${dest}"
    git clone --filter=blob:none "${IPEM_REPO}" "${dest}"
    git -C "${dest}" checkout --force "${IPEM_REF}"
  fi
  git -C "${dest}" rev-parse HEAD > "${BUILD_DIR}/IPEM_REF_RESOLVED"
  # Guard from PR #3 must be present for deployed Runtime.
  grep -q 'isdeployed' "${dest}/IPEMToolbox/IPEMSetup.m" \
    || die "IPEMSetup.m at ${IPEM_REF} is missing the isdeployed path2rc guard"
}

build_mex() {
  local ipem="$1"
  local matlab_root="$2"
  local mex_dir="${ipem}/AuditoryModel/Matlab8_UNIX"
  log "Building IPEM mexa64 against ${matlab_root}"
  mkdir -p "${mex_dir}/Release"
  make -C "${mex_dir}" \
    MATLAB_DIR="${matlab_root}" \
    MEX_EXT=mexa64 \
    clean all install
  test -f "${ipem}/IPEMToolbox/Common/IPEMProcessAuditoryModelSafe.mexa64" \
    || die "mex install did not produce IPEMProcessAuditoryModelSafe.mexa64"
}

compile_worker() {
  local ipem="$1"
  local matlab_root="$2"
  local out="$3"
  log "Compiling leman_2000_worker with mcc"
  rm -rf "${out}"
  mkdir -p "${out}"
  # -I picks up shared helpers; -a packs the whole IPEM toolbox into the CTF.
  "${matlab_root}/bin/mcc" \
    -m "${MATLAB_SRC}/leman_2000_worker.m" \
    -I "${MATLAB_SRC}" \
    -a "${ipem}/IPEMToolbox" \
    -d "${out}"
  test -x "${out}/leman_2000_worker" || die "mcc did not produce leman_2000_worker"
  test -f "${out}/buildresult.json" || die "mcc did not produce buildresult.json"
  cp "${out}/buildresult.json" "${BUILD_DIR}/buildresult.json"
  cp "${out}/requiredMCRProducts.txt" "${BUILD_DIR}/requiredMCRProducts.txt"
}

package_docker_images() {
  local matlab_root="$1"
  local worker_dir="$2"
  local context="$3"
  log "Creating custom Runtime + worker Docker images via MATLAB Compiler"
  rm -rf "${context}"
  mkdir -p "${context}"
  export PYLEMAN_BUILD_WORKER_DIR="${worker_dir}"
  export PYLEMAN_RUNTIME_IMAGE="${RUNTIME_IMAGE}"
  export PYLEMAN_WORKER_IMAGE="${LOCAL_IMAGE}"
  export PYLEMAN_DOCKER_CONTEXT="${context}"
  # -batch keeps this headless; Compiler APIs need a licensed MATLAB session.
  "${matlab_root}/bin/matlab" -batch \
    "addpath('${MATLAB_SRC}'); package_matlab_worker();"
  docker image inspect "${LOCAL_IMAGE}" >/dev/null \
    || die "expected Docker image ${LOCAL_IMAGE} was not created"
}

smoke_test() {
  local image="$1"
  local smoke_dir="$2"
  local wav="${ROOT}/src/pyleman2000/data/hihat.wav"
  [[ -f "${wav}" ]] || die "missing packaged hihat at ${wav}"

  log "Smoke-testing ${image}"
  rm -rf "${smoke_dir}"
  mkdir -p "${smoke_dir}/work" "${smoke_dir}/data"
  cp "${wav}" "${smoke_dir}/data/hihat.wav"

  local name="pyleman-matlab-smoke-$$"
  docker rm -f "${name}" >/dev/null 2>&1 || true
  docker run -d --name "${name}" \
    -e AGREE_TO_MATLAB_RUNTIME_LICENSE=yes \
    -e MLM_LICENSE_FILE=/definitely/not/a/license.lic \
    -v "${smoke_dir}/work:/work" \
    -v "${smoke_dir}/data:/data" \
    "${image}" \
    /work >/dev/null

  python3 - "${smoke_dir}" "${name}" <<'PY'
import json, os, sys, time, subprocess
from pathlib import Path

smoke = Path(sys.argv[1])
name = sys.argv[2]
work = smoke / "work"
ready = work / "ready"
deadline = time.monotonic() + 180
while not ready.exists():
    running = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", name],
        capture_output=True, text=True,
    ).stdout.strip()
    if running != "true":
        logs = subprocess.run(["docker", "logs", name], capture_output=True, text=True)
        raise SystemExit(f"worker died before ready\n{logs.stdout}\n{logs.stderr}")
    if time.monotonic() > deadline:
        raise SystemExit("timed out waiting for ready")
    time.sleep(0.05)

payload = {
    "in_file": "/data/hihat.wav",
    "out_file": "/data/out.json",
    "local_decay_sec": [0.1],
    "global_decay_sec": [1.0],
    "detail": 0,
}
tmp = work / "tmp-req-smoke.json"
tmp.write_text(json.dumps(payload))
os.replace(tmp, work / "req-smoke.json")

res = work / "res-smoke.json"
deadline = time.monotonic() + 180
while not res.exists():
    if time.monotonic() > deadline:
        raise SystemExit("timed out waiting for response")
    time.sleep(0.05)
status = json.loads(res.read_text())
if status.get("status") != "ok":
    raise SystemExit(f"worker error: {status}")
out = json.loads((smoke / "data" / "out.json").read_text())
assert "local_global_comparison" in out
print(
    "SMOKE_OK audio=%.6f combos=%d"
    % (out["audio_length_sec"], len(out["local_global_comparison"]))
)
PY

  touch "${smoke_dir}/work/stop"
  docker rm -f "${name}" >/dev/null
}

write_provenance() {
  local matlab_root="$1"
  local out="${BUILD_DIR}/PROVENANCE.txt"
  {
    echo "built_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "host=$(hostname)"
    echo "ipem_repo=${IPEM_REPO}"
    echo "ipem_ref_requested=${IPEM_REF}"
    echo "ipem_ref_resolved=$(cat "${BUILD_DIR}/IPEM_REF_RESOLVED")"
    echo "matlab_root=${matlab_root}"
    echo "matlab_version=$("${matlab_root}/bin/matlab" -batch "disp(version)" | tail -1)"
    echo "local_image=${LOCAL_IMAGE}"
    echo "runtime_image=${RUNTIME_IMAGE}"
    echo "image_id=$(docker image inspect --format '{{.Id}}' "${LOCAL_IMAGE}")"
    echo "image_size=$(docker image inspect --format '{{.Size}}' "${LOCAL_IMAGE}")"
  } > "${out}"
  log "Wrote ${out}"
  cat "${out}"
}

push_image() {
  log "Tagging and pushing ${GHCR_TAG}"
  docker tag "${LOCAL_IMAGE}" "${GHCR_TAG}"
  if [[ "${IMAGE_TAG}" != "dev" ]]; then
    docker tag "${LOCAL_IMAGE}" "${GHCR_IMAGE}:latest"
  fi
  docker push "${GHCR_TAG}"
  if [[ "${IMAGE_TAG}" != "dev" ]]; then
    docker push "${GHCR_IMAGE}:latest"
  fi
  docker image inspect --format '{{index .RepoDigests 0}}' "${GHCR_TAG}" \
    | tee "${BUILD_DIR}/GHCR_DIGEST.txt"
}

main() {
  require_linux_amd64
  require_tools
  local matlab_root
  matlab_root="$(resolve_matlab_root)"
  log "Using MATLAB at ${matlab_root}"
  [[ -x "${matlab_root}/bin/mcc" ]] || die "mcc not found under ${matlab_root}/bin (Compiler required)"

  mkdir -p "${BUILD_DIR}"
  local ipem="${BUILD_DIR}/ipem"
  local worker_out="${BUILD_DIR}/mcc-worker"
  local docker_context="${BUILD_DIR}/docker-context"
  local smoke_dir="${BUILD_DIR}/smoke"

  clone_ipem "${ipem}"
  build_mex "${ipem}" "${matlab_root}"
  compile_worker "${ipem}" "${matlab_root}" "${worker_out}"
  package_docker_images "${matlab_root}" "${worker_out}" "${docker_context}"

  if [[ "${SKIP_SMOKE}" -eq 0 ]]; then
    smoke_test "${LOCAL_IMAGE}" "${smoke_dir}"
  else
    log "Skipping smoke test (--skip-smoke)"
  fi

  write_provenance "${matlab_root}"

  if [[ "${PUSH}" -eq 1 ]]; then
    push_image
  else
    log "Built ${LOCAL_IMAGE}. Re-run with --push to publish ${GHCR_TAG}."
  fi

  log "Done."
  echo
  echo "Local override:"
  echo "  leman2000(..., backend='matlab', docker_image='${LOCAL_IMAGE}')"
  echo "Session:"
  echo "  Leman2000Session(backend='matlab', docker_image='${LOCAL_IMAGE}')"
}

main "$@"
