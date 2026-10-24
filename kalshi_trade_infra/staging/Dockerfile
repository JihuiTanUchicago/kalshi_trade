FROM python:3.12-slim

WORKDIR /srv/tau-paper-staging
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY requirements.txt requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt

# Explicit copies exclude private environments, credentials, runtime state and
# repository metadata. Keep the complete application packages together.
COPY app/ app/
COPY data_pipeline/ data_pipeline/
COPY staging/entrypoint.py /usr/local/lib/tau-staging/entrypoint.py
COPY scripts/paper_staging_smoke.py scripts/paper_staging_smoke.py
COPY scripts/kalshi_perps_staging_smoke.py scripts/kalshi_perps_staging_smoke.py

# Bootstrap reads host-private bind secrets, then permanently drops uid/gid and
# supplementary groups before executing any application code.
ENTRYPOINT ["/usr/local/bin/python", "-I", "-B", "/usr/local/lib/tau-staging/entrypoint.py"]
CMD ["web"]
