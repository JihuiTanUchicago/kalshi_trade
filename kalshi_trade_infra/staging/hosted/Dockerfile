FROM python:3.12-slim
WORKDIR /srv/tau-hosted-preproduction
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY requirements.txt requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY app/ app/
COPY data_pipeline/ data_pipeline/
COPY staging/hosted/entrypoint.py /usr/local/lib/tau-hosted/entrypoint.py
ENTRYPOINT ["/usr/local/bin/python", "-I", "-B", "/usr/local/lib/tau-hosted/entrypoint.py"]
CMD ["web"]
