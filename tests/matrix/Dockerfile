FROM python:3.11-slim-bookworm

ARG KLIPPER_REF

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc git libc6-dev libffi-dev \
    && rm -rf /var/lib/apt/lists/*

RUN test -n "${KLIPPER_REF}" \
    && git init /opt/klipper \
    && git -C /opt/klipper remote add origin https://github.com/Klipper3d/klipper.git \
    && git -C /opt/klipper fetch --depth 1 origin "${KLIPPER_REF}" \
    && git -C /opt/klipper checkout --detach FETCH_HEAD \
    && test "$(git -C /opt/klipper rev-parse HEAD)" = "${KLIPPER_REF}"

RUN python -m pip install --no-cache-dir -r /opt/klipper/scripts/klippy-requirements.txt

COPY tests/matrix/klipper_validator.py /usr/local/bin/kace-klipper-validator

ENV KLIPPER_ROOT=/opt/klipper
ENTRYPOINT ["python", "/usr/local/bin/kace-klipper-validator"]
