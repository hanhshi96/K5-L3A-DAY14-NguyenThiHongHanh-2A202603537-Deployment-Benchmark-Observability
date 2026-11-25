"""
Rate limiting (tiêu chí 7).

Yêu cầu:
  • Mỗi API key tối đa RATE_LIMIT_PER_MINUTE request trong 60 giây (sliding window)
  • Vượt giới hạn → HTTP 429, nên kèm header Retry-After
  • State lưu trong Redis để mọi worker / instance dùng chung và vẫn còn sau khi
    restart agent (script chấm sẽ restart agent để kiểm tra)
"""
import hashlib
import time
import uuid

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60


def check_rate_limit(key: str) -> None:
    limit = settings.rate_limit_per_minute
    # Không lưu API key gốc trong Redis — chỉ lưu bản băm (hash)
    bucket = "ratelimit:" + hashlib.sha256(key.encode()).hexdigest()[:16]
    now = time.time()
    member = f"{now}-{uuid.uuid4().hex[:8]}"

    # Chạy 4 lệnh như 1 khối (transaction) → 2 worker cùng lúc cũng không đếm sai
    pipe = r.pipeline()
    pipe.zremrangebyscore(bucket, 0, now - WINDOW_SECONDS)  # xoá request cũ hơn 60s
    pipe.zadd(bucket, {member: now})                         # ghi request này
    pipe.zcard(bucket)                                       # đếm số request trong 60s
    pipe.expire(bucket, WINDOW_SECONDS)                      # tự dọn key khi hết dùng
    _, _, count, _ = pipe.execute()

    if count > limit:
        r.zrem(bucket, member)  # request bị chặn thì không tính
        oldest = r.zrange(bucket, 0, 0, withscores=True)
        retry_after = int(oldest[0][1] + WINDOW_SECONDS - now) + 1 if oldest else WINDOW_SECONDS
        raise HTTPException(
            status_code=429,
            detail={"error": "Rate limit exceeded", "limit": limit, "window_seconds": WINDOW_SECONDS},
            headers={"Retry-After": str(retry_after)},
        )
