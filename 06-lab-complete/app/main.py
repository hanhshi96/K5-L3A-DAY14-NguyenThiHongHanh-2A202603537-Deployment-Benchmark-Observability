"""
Production AI Agent — Part 6 Final Project (bản khung)

Hoàn thành các TODO để đạt đủ 12 tiêu chí trong README.md, rồi kiểm tra:
    python check_production_ready.py

Bản khung này chạy được (uvicorn app.main:app) nhưng chưa đạt tiêu chí nào.
"""
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import redis
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import r as redis_client
from app.redis_client import redis_healthy
from utils.mock_llm import ask as llm_ask


# ── Structured logging (tiêu chí 10): mỗi dòng log = 1 JSON object ──
class JsonFormatter(logging.Formatter):
    """Mỗi dòng log = 1 JSON object."""

    def format(self, record):
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "lvl": record.levelname,
            "event": record.getMessage(),
        }
        payload.update(getattr(record, "fields", {}))  # thông tin thêm: path, status, ms...
        return json.dumps(payload, ensure_ascii=False)


_handler = logging.StreamHandler()
_handler.setFormatter(JsonFormatter())
logger = logging.getLogger("agent")
logger.handlers = [_handler]
logger.setLevel(logging.INFO)
logger.propagate = False  # không đẩy sang root logger → không bị in trùng

START_TIME = time.time()


# ── Graceful shutdown (tiêu chí 11) ──
# Khi nhận SIGTERM, uvicorn tự ngừng nhận request mới và chờ request đang chạy xong,
# sau đó mới chạy phần sau `yield`. KHÔNG tự đăng ký signal handler cho SIGTERM
# (sẽ đè mất handler của uvicorn → process không bao giờ tắt).
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ── (không ping Redis ở đây → vẫn khởi động được khi Redis chưa sẵn sàng)
    logger.info("startup", extra={"fields": {
        "environment": settings.environment,
        "rate_limit_per_minute": settings.rate_limit_per_minute,
        "daily_budget_usd": settings.daily_budget_usd,
    }})
    yield
    # ── Shutdown ── request đang chạy đã xong, dọn dẹp kết nối
    logger.info("shutdown", extra={"fields": {"uptime_seconds": round(time.time() - START_TIME, 1)}})
    redis_client.close()  # đóng kết nối Redis


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Ghi 1 dòng log JSON cho mỗi request (không log API key / nội dung câu hỏi)."""
    start = time.perf_counter()
    response = await call_next(request)
    logger.info("request", extra={"fields": {
        "method": request.method,
        "path": request.url.path,
        "status": response.status_code,
        "ms": round((time.perf_counter() - start) * 1000, 1),
    }})
    return response


@app.exception_handler(redis.RedisError)
async def redis_error_handler(request: Request, exc: redis.RedisError):
    """Redis chết giữa chừng → 503 gọn gàng, không lộ stack trace."""
    logger.error("redis_error", extra={"fields": {"path": request.url.path, "error": type(exc).__name__}})
    return JSONResponse(status_code=503, content={"detail": "Service temporarily unavailable"})


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


def _estimate_tokens(text: str) -> int:
    """Mock LLM không trả số token → ước lượng ~4 ký tự = 1 token."""
    return max(1, len(text) // 4)


# ── Liveness (tiêu chí 4): luôn 200 khi process còn chạy, không phụ thuộc Redis ──
@app.get("/health")
def health():
    """Liveness: luôn 200 khi process còn chạy — KHÔNG phụ thuộc Redis."""
    return {
        "status": "ok",
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "environment": settings.environment,
    }


# ── Readiness (tiêu chí 5): 200 khi sẵn sàng, 503 khi Redis không kết nối được ──
@app.get("/ready")
def ready():
    """Readiness: 200 khi Redis kết nối được, 503 khi không."""
    if not redis_healthy():
        raise HTTPException(status_code=503, detail="Not ready: Redis unreachable")
    return {"ready": True, "redis": "ok"}


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)  # tiêu chí 7: vượt giới hạn → 429 (state trong Redis)
    check_budget()             # tiêu chí 8: hết budget → 402, KHÔNG gọi LLM
    answer = llm_ask(body.question)
    cost = record_cost(_estimate_tokens(body.question), _estimate_tokens(answer))
    return {"question": body.question, "answer": answer, "usage": {"cost_usd": round(cost, 8)}}
