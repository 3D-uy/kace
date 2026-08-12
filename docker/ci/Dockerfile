# Dockerfile — KACE Simulation & Development Container
FROM python:3.11-slim-bookworm@sha256:d29f48a31a8b408ed19272ca1e7b10ebae13b240a27e862d3d4217c528e2e0c3

# Install required system packages (including ARM and AVR cross-compilation toolchains)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    procps \
    build-essential \
    gcc-arm-none-eabi \
    binutils-arm-none-eabi \
    libnewlib-arm-none-eabi \
    gcc-avr \
    binutils-avr \
    avr-libc \
    && rm -rf /var/lib/apt/lists/*

# Set up workspace
WORKDIR /workspace

# Pre-install python package requirements
COPY requirements.txt requirements-ssh.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements.txt \
    && pip install --no-cache-dir --require-hashes -r requirements-ssh.txt

# Set up mock systemctl to intercept systemd service checks in KACE dashboard
COPY docker/ci/mock_systemctl /usr/local/bin/systemctl
RUN chmod +x /usr/local/bin/systemctl

# Set up mock make to intercept Klipper firmware compilation
COPY docker/ci/mock_make /usr/local/bin/make
RUN chmod +x /usr/local/bin/make

# Expose Moonraker API mock port
EXPOSE 7125

# Run the entrypoint script
CMD ["/bin/bash", "/workspace/docker/ci/entrypoint.sh"]
