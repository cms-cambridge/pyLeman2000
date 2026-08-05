# Leman (2000) Octave backend for pyLeman2000.
#
# Builds a license-free image from the Octave-compatible IPEM Toolbox fork.
# The container entrypoint matches the MATLAB MCR image CLI so
# pyleman2000.docker_runner can use either backend unchanged:
#
#   /leman_2000_docker.sh <input.wav> <output.json> <local_csv> <global_csv> <detail>
#
# Build (from the pyLeman2000 repository root):
#
#   docker build -f docker/octave/Dockerfile -t pyleman2000-octave:dev docker/octave
#
# Pin IPEM_REF to a commit SHA of cms-cambridge/IPEMToolbox for reproducibility.

ARG OCTAVE_BASE=docker.io/gnuoctave/octave:10.3.0
FROM ${OCTAVE_BASE}

USER root

ARG IPEM_REPO=https://github.com/cms-cambridge/IPEMToolbox.git
# Pin to the Octave-compat fork revision (update when merging toolbox PRs).
ARG IPEM_REF=fc2dc4f9dbcd9df50da16a5e1a228284e9d81cd0

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

COPY leman_2000.m /opt/leman_2000.m
COPY leman_2000_docker.sh /leman_2000_docker.sh
RUN chmod +x /leman_2000_docker.sh

WORKDIR /opt
ENTRYPOINT ["/leman_2000_docker.sh"]
