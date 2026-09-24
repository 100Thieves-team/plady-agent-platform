# qa-platform — docs/qa-platform.md. 표준 라이브러리 + PyYAML 만 쓴다.
FROM python:3.12-alpine
RUN pip install --no-cache-dir --disable-pip-version-check "PyYAML==6.0.3"
WORKDIR /app
COPY qa-platform/app.py /app/app.py
COPY qa-platform/qa /app/qa
COPY qa-platform/cases /app/cases
COPY qa-platform/catalog /app/catalog
COPY qa-platform/scenarios /app/scenarios
ENV QA_PORT=8800 QA_DATA_DIR=/data QA_CASES_DIR=/app/cases QA_CATALOG_DIR=/app/catalog QA_SCENARIOS_DIR=/app/scenarios PYTHONUNBUFFERED=1
VOLUME ["/data"]
EXPOSE 8800
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8800/health', timeout=4).status == 200 else 1)"
CMD ["python", "/app/app.py"]
