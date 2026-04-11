from datetime import datetime, timezone
from typing import List, Optional

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import coingecko
from app.auth import get_current_user
from app.database import get_db
from app.models import Coin, User
from app.schemas import CoinOut

router = APIRouter(prefix="/api/coins", tags=["coins"])


def _now():
    return datetime.now(timezone.utc)


@router.get("/top", response_model=List[CoinOut])
async def get_top_coins(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Fetch top coins from CoinGecko and upsert into local DB. Falls back to DB on CoinGecko failure."""
    try:
        raw = await coingecko.fetch_top_coins(limit)
    except Exception:
        # CoinGecko unavailable — serve cached DB rows instead of crashing
        result = await db.execute(
            select(Coin).where(Coin.last_updated.isnot(None)).order_by(Coin.market_cap.desc()).limit(limit)
        )
        return result.scalars().all()

    coins_out = []
    for item in raw:
        result = await db.execute(select(Coin).where(Coin.coingecko_id == item["id"]))
        coin = result.scalar_one_or_none()
        if coin is None:
            coin = Coin(coingecko_id=item["id"], symbol=item["symbol"], name=item["name"])
            db.add(coin)
        coin.current_price_usd = item.get("current_price")
        coin.price_change_24h = item.get("price_change_percentage_24h")
        coin.market_cap = item.get("market_cap")
        coin.image_url = item.get("image")
        coin.last_updated = _now()
        coins_out.append(coin)

    await db.commit()
    for c in coins_out:
        await db.refresh(c)
    return coins_out


@router.get("/search", response_model=List[dict])
async def search_coins(
    q: str = Query(..., min_length=1),
    _: User = Depends(get_current_user),
):
    return await coingecko.search_coins(q)


@router.get("/{coingecko_id}/history")
async def price_history(
    coingecko_id: str,
    days: int = Query(30, ge=1, le=365),
    _: User = Depends(get_current_user),
):
    try:
        raw = await coingecko.fetch_price_history(coingecko_id, days)
    except aiohttp.ClientResponseError as e:
        msg = "CoinGecko rate limit — try again in a moment" if e.status == 429 else f"CoinGecko error {e.status}"
        raise HTTPException(status_code=502, detail=msg)
    except Exception as e:
        raise HTTPException(status_code=502, detail="Failed to fetch price history from CoinGecko")
    return {"coingecko_id": coingecko_id, "prices": [{"timestamp": p[0], "price": p[1]} for p in raw]}
