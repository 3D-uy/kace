FROM python:3.11-slim-bookworm@sha256:d29f48a31a8b408ed19272ca1e7b10ebae13b240a27e862d3d4217c528e2e0c3

# Real, non-mocked Klipper build environment used to verify BoardContract
# targets on development hosts that do not provide the cross toolchain.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        binutils-arm-none-eabi \
        build-essential \
        gcc-arm-none-eabi \
        git \
        libnewlib-arm-none-eabi \
        make \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-dev.txt ./requirements-dev.txt
RUN pip install --no-cache-dir --require-hashes -r requirements-dev.txt

WORKDIR /workspace
