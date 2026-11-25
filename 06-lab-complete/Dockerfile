# ============================================================
# Production Dockerfile — Part 6 (tiêu chí 1)
#   • Multi-stage: builder cài dependencies, runtime chỉ copy kết quả
#   • Base python:3.11-slim, chạy bằng user non-root
#   • HEALTHCHECK gọi GET /health
#   • CMD đọc biến PORT (mặc định 8000), `exec` → uvicorn là PID 1 nhận SIGTERM
# ============================================================

# ── Stage 1: builder — cài thư viện vào /install ──
FROM python:3.11-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: runtime — chỉ copy thư viện đã cài + code ──
FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000
RUN groupadd -r app && useradd -r -g app -d /app app
WORKDIR /app
COPY --from=builder /install /usr/local
COPY --chown=app:app app/ ./app/
COPY --chown=app:app utils/ ./utils/
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request as u; u.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','8000'), timeout=3)" || exit 1
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2 --timeout-graceful-shutdown 8"]
