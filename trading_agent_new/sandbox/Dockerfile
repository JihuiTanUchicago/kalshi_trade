# Build explicitly, then record `docker image inspect --format '{{.Id}}' IMAGE`.
# Runtime uses that image ID with --pull=never; it never installs dependencies.
FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c
COPY requirements.txt /requirements.txt
RUN pip install --no-cache-dir -r /requirements.txt
COPY runner.py /runner.py
USER 65534:65534
ENTRYPOINT []
