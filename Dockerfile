# Use an official lightweight Python runtime
FROM python:3.12-slim

# Install git (required for the config generator/sweep if used) and SSH client
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Copy the current project files into the container
COPY . /app

# Pre-install paramiko (KACE does this lazily, but it's faster to bake it in)
RUN pip install --no-cache-dir paramiko==3.4.0

# Ensure kace.py is executable
RUN chmod +x kace.py

# Set the entrypoint so the container acts exactly like the KACE binary
ENTRYPOINT ["python3", "kace.py"]
