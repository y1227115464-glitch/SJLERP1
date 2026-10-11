ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app/apps/api
COPY apps/api/requirements.lock ./requirements.lock
COPY infra/nas/requirements-extra.lock ./requirements-extra.lock
RUN pip install --no-cache-dir -r requirements.lock -r requirements-extra.lock \
    && useradd --uid 10001 --create-home sjlerp \
    && mkdir -p /data/storage && chown -R sjlerp:sjlerp /data
COPY apps/api/ ./
COPY scripts/nas_master_data.py /app/scripts/nas_master_data.py
RUN chown -R sjlerp:sjlerp /app && chmod -R u+rX /app
USER sjlerp
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
