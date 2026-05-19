FROM python:3.11-slim AS build
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir sqlalchemy alembic cryptography bcrypt

FROM python:3.11-slim
WORKDIR /app
RUN useradd --create-home --shell /bin/bash app
COPY --from=build /usr/local /usr/local
COPY . .
RUN chown -R app:app /app
USER app
ENV PYTHONPATH=/app/src
ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=5).read()" || exit 1
CMD ["streamlit", "run", "src/wealthtax_agent/main.py", "--server.headless=true", "--server.port=8501", "--server.address=0.0.0.0"]
