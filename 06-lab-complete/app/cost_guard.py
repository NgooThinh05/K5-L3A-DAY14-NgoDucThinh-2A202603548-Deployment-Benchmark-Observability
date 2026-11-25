"""
Cost guard (tiêu chí 8).
Cộng dồn chi phí LLM theo token vào Redis; vượt DAILY_BUDGET_USD hoặc MONTHLY_BUDGET_USD → HTTP 402.
"""
from datetime import datetime, timezone

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006


def _daily_key() -> str:
    return f"cost:daily:{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"


def _monthly_key() -> str:
    return f"cost:monthly:{datetime.now(timezone.utc).strftime('%Y-%m')}"


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    if settings.daily_budget_usd <= 0 or settings.monthly_budget_usd <= 0:
        raise HTTPException(status_code=402, detail="Budget limit reached")

    if r is None:
        raise HTTPException(status_code=503, detail="Budget storage unavailable")

    try:
        daily_spent = float(r.get(_daily_key()) or 0.0)
        monthly_spent = float(r.get(_monthly_key()) or 0.0)
    except Exception:
        raise HTTPException(status_code=503, detail="Budget storage unavailable")

    if daily_spent >= settings.daily_budget_usd:
        raise HTTPException(
            status_code=402,
            detail=f"Daily budget exceeded (${daily_spent:.6f} / ${settings.daily_budget_usd:.4f})",
        )
    if monthly_spent >= settings.monthly_budget_usd:
        raise HTTPException(
            status_code=402,
            detail=f"Monthly budget exceeded (${monthly_spent:.6f} / ${settings.monthly_budget_usd:.4f})",
        )


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí request vào Redis, trả về chi phí request."""
    cost = (
        (input_tokens / 1000.0) * PRICE_INPUT_PER_1K
        + (output_tokens / 1000.0) * PRICE_OUTPUT_PER_1K
    )

    if r is not None:
        try:
            d_key = _daily_key()
            m_key = _monthly_key()
            pipe = r.pipeline()
            pipe.incrbyfloat(d_key, cost)
            pipe.expire(d_key, 2 * 86400)
            pipe.incrbyfloat(m_key, cost)
            pipe.expire(m_key, 35 * 86400)
            pipe.execute()
        except Exception:
            pass

    return round(cost, 8)
