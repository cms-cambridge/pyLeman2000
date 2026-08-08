# Leman (2000) Octave backend for pyLeman2000.
#
# linux/amd64 image based on gnuoctave/octave:10.3.0 (Hub tags are amd64-only;
# Apple Silicon users run via Docker Desktop Rosetta/QEMU). The IPEM mex is
# compiled in-image.
#
# Entrypoint:
#   /leman_2000_docker.sh <input.wav> <output.json> <local_csv> <global_csv> <detail>
#
# Local build (from the repository root):
#   ./scripts/build_octave_image.sh
#
# Published image (CI):
#   ghcr.io/cms-cambridge/pyleman2000-octave:0.1.0

ARG OCTAVE_BASE=docker.io/gnuoctave/octave:10.3.0
FROM ${OCTAVE_BASE}

USER root

ARG IPEM_REPO=https://github.com/cms-cambridge/IPEMToolbox.git
# Pin to the Octave-compat fork revision on master.
ARG IPEM_REF=052b79fa984a7b02808f1306cc201d5b0767a7a3

ENV DEBIAN_FRONTEND=noninteractive \
    OCTAVE_HISTFILE=/tmp/octave-history \
    IPEM_ROOT=/opt/IPEMToolbox \
    LD_LIBRARY_PATH=

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        git \
        libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

RUN octave --no-gui --quiet --eval "\
  pkg install -forge io; \
  pkg install -forge control; \
  pkg install -forge signal; \
  pkg list;"

RUN git clone --filter=blob:none "${IPEM_REPO}" "${IPEM_ROOT}" \
    && cd "${IPEM_ROOT}" \
    && git checkout "${IPEM_REF}" \
    && mkdir -p AuditoryModel/Octave_UNIX/Release IPEMToolbox/Temp \
    && cd AuditoryModel/Octave_UNIX \
    && make \
    && make install \
    && test -f "${IPEM_ROOT}/IPEMToolbox/Common/IPEMProcessAuditoryModelSafe.mex"

# Streaming / spool helpers shared with the MATLAB backend (build context =
# repository root).
COPY docker/matlab/leman_calc_ani_spool.m \
     docker/matlab/leman_read_ani_chunk.m \
     docker/matlab/leman_downsample_ani_init.m \
     docker/matlab/leman_downsample_ani_chunk.m \
     docker/matlab/leman_ani_from_spool_chunk.m \
     docker/matlab/leman_periodicity_pitch_chunk.m \
     docker/matlab/leman_periodicity_pitch_from_spool.m \
     docker/matlab/leman_leaky_integration_chunk.m \
     docker/matlab/leman_contextuality_comparison_stream.m \
     /opt/pyleman_helpers/

COPY docker/octave/leman_2000.m /opt/leman_2000.m
COPY docker/octave/leman_2000_docker.sh /leman_2000_docker.sh
RUN chmod +x /leman_2000_docker.sh

WORKDIR /opt
ENTRYPOINT ["/leman_2000_docker.sh"]
