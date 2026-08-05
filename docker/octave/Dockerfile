# Leman (2000) Octave backend for pyLeman2000 (multi-arch).
#
# Builds GNU Octave 10.3 from source on ubuntu:24.04 so the same recipe works
# for linux/amd64 and linux/arm64 (the Hub gnuoctave/octave tags are amd64-only).
# The IPEM mex is compiled natively in-image for the target architecture.
#
# Entrypoint:
#   /leman_2000_docker.sh <input.wav> <output.json> <local_csv> <global_csv> <detail>
#
# Local (native arch):
#   ./scripts/build_octave_image.sh
#
# Published multi-arch image (CI):
#   ghcr.io/cms-cambridge/pyleman2000-octave:0.1.0

ARG UBUNTU_IMAGE=docker.io/library/ubuntu:24.04
FROM ${UBUNTU_IMAGE}

ARG OCTAVE_VERSION=10.3.0
ARG GNU_MIRROR=https://ftpmirror.gnu.org/octave
ARG IPEM_REPO=https://github.com/cms-cambridge/IPEMToolbox.git
# Pin to the Octave-compat fork revision on master.
ARG IPEM_REF=052b79fa984a7b02808f1306cc201d5b0767a7a3

ENV DEBIAN_FRONTEND=noninteractive \
    OCTAVE_HISTFILE=/tmp/octave-history \
    IPEM_ROOT=/opt/IPEMToolbox \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        gfortran \
        git \
        libarpack2-dev \
        libcurl4-gnutls-dev \
        libfftw3-dev \
        libglpk-dev \
        libhdf5-dev \
        libopenblas-dev \
        libpcre2-dev \
        libqhull-dev \
        libqrupdate-dev \
        libreadline-dev \
        libsndfile1 \
        libsndfile1-dev \
        libsuitesparse-dev \
        libsundials-dev \
        pkg-config \
        tar \
        wget \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# CLI-only Octave build shared by amd64 and arm64.
RUN mkdir -p /tmp/build \
    && cd /tmp/build \
    && wget -q "${GNU_MIRROR}/octave-${OCTAVE_VERSION}.tar.gz" \
    && tar -xzf "octave-${OCTAVE_VERSION}.tar.gz" \
    && cd "octave-${OCTAVE_VERSION}" \
    && ./configure \
        --prefix=/usr/local \
        --without-qt \
        --without-fltk \
        --without-opengl \
        --disable-java \
        --disable-docs \
        --with-blas=-lopenblas \
    && make -j"$(nproc)" \
    && make install \
    && ldconfig \
    && cd / \
    && rm -rf /tmp/build \
    && octave --version | head -n 1

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
