ARG base_tag=bullseye
ARG base_img=mcr.microsoft.com/vscode/devcontainers/python:3.10-${base_tag}

FROM ${base_img} AS builder-install

# Base image ships a stale Yarn apt repo whose GPG key has rotated; we use npm, not yarn.
RUN rm -f /etc/apt/sources.list.d/yarn.list

# Dependencies for C
RUN apt-get update --fix-missing && apt-get -y upgrade && apt-get install -y --no-install-recommends \
    apt-utils \
    curl \
    cmake \
    build-essential \
    gdb \
    ninja-build \
    locales \
    make \
    ruby \
    gcovr \
    wget \
    libx11-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

ENV LANG='en_US.UTF-8' LANGUAGE='en_US:en' LC_ALL='en_US.UTF-8'

RUN echo 'en_US.UTF-8 UTF-8' > /etc/locale.gen && /usr/sbin/locale-gen
RUN echo "alias ll='ls -laGFh'" >> /root/.bashrc

VOLUME ["/workspaces/gamequeer"]
WORKDIR /workspaces/gamequeer

# install clang tools

ARG base_tag=bullseye
ARG llvm_version=16
RUN apt-get update --fix-missing && apt-get -y upgrade && apt-get install -y --no-install-recommends \
    gnupg2 \
    gnupg-agent \
    ca-certificates \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /etc/apt/keyrings \
    && curl --fail --silent --show-error --location \
        --retry 5 --retry-delay 5 --retry-all-errors --connect-timeout 15 \
        --output /tmp/llvm-snapshot.asc https://apt.llvm.org/llvm-snapshot.gpg.key \
    && gpg --dearmor --output /etc/apt/keyrings/llvm-snapshot.gpg /tmp/llvm-snapshot.asc \
    && rm -f /tmp/llvm-snapshot.asc
RUN echo "deb [signed-by=/etc/apt/keyrings/llvm-snapshot.gpg] http://apt.llvm.org/$base_tag/ llvm-toolchain-$base_tag-$llvm_version main" >> /etc/apt/sources.list.d/llvm.list

RUN apt-get update --fix-missing && apt-get -y upgrade && apt-get install -y --no-install-recommends \
    clang-format-${llvm_version} \
    clang-tidy-${llvm_version} \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN ln -s /usr/bin/clang-format-${llvm_version} /usr/local/bin/clang-format
RUN ln -s /usr/bin/clang-tidy-${llvm_version} /usr/local/bin/clang-tidy

# RUN mkdir -p /usr/local/run-clang-format
# RUN wget -O clang-utils.tgz "https://github.com/lmapii/run-clang-format/releases/download/v1.4.10/run-clang-format-v1.4.10-i686-unknown-linux-gnu.tar.gz" && \
#     tar -C /usr/local/run-clang-format -xzf clang-utils.tgz --strip-components 1 && \
#     rm clang-utils.tgz

# ENV PATH /usr/local/run-clang-format:$PATH
# RUN run-clang-format --version

# RUN mkdir -p /usr/local/run-clang-tidy
# RUN wget -O clang-utils.tgz "https://github.com/lmapii/run-clang-tidy/releases/download/v0.2.1/run-clang-tidy-v0.2.1-i686-unknown-linux-gnu.tar.gz" && \
#     tar -C /usr/local/run-clang-tidy -xzf clang-utils.tgz --strip-components 1 && \
#     rm clang-utils.tgz

# ENV PATH /usr/local/run-clang-tidy:$PATH
# RUN run-clang-format --version

# install unity cmock and ceedling (unit test environment)
RUN gem install ceedling
# set standard encoding to UTF-8 for ruby (and thus ceedling)
ENV RUBYOPT="-KU -E utf-8:utf-8"

# Node stuff for langium:
COPY --chmod=0774 gq-game-language/install-langium-deps.sh /workspaces/gamequeer/gq-game-language/
RUN /workspaces/gamequeer/gq-game-language/install-langium-deps.sh

# Python dependencies

RUN apt-get update --fix-missing && apt-get -y upgrade && apt-get install -y --no-install-recommends \
    ffmpeg \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /workspaces/gamequeer/
RUN pip install --upgrade pip && pip install --requirement /workspaces/gamequeer/requirements.txt

# Put the dev python gqc module in the python path
ENV PYTHONPATH=$PYTHONPATH:/workspaces/gamequeer/gqc/src/:/workspaces/gamequeer/gqc/src/
ENV PATH="/workspaces/gamequeer/build/:$PATH"

# `gqc` console shim: this image runs gqc straight off PYTHONPATH above (no
# pip/uv install of the package itself), but gqc's generated workspace
# Makefile defaults GQC_CMD to a bare `gqc` on PATH (see
# gqc/src/gqc/makefile_src.py) -- as does anything else expecting the
# `uv tool install` layout.
RUN printf '#!/bin/sh\nexec python -m gqc "$@"\n' > /usr/local/bin/gqc && chmod +x /usr/local/bin/gqc
