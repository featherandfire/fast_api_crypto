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


@router.get("/top")
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

    # Merge supply fields from raw CoinGecko data (not stored in DB)
    supply_map = {item["id"]: item for item in raw}
    result = []
    for coin in coins_out:
        row = CoinOut.model_validate(coin).model_dump()
        raw_item = supply_map.get(coin.coingecko_id, {})
        row["circulating_supply"]        = raw_item.get("circulating_supply")
        row["max_supply"]                = raw_item.get("max_supply")
        row["price_change_200d"]         = raw_item.get("price_change_percentage_200d_in_currency")
        row["price_change_1y"]           = raw_item.get("price_change_percentage_1y_in_currency")
        result.append(row)
    return result


@router.get("/yearly-ranges")
async def get_yearly_ranges(
    ids: str = Query(..., description="Comma-separated CoinGecko IDs"),
    _: User = Depends(get_current_user),
):
    """Return 1-year high/low keyed by coingecko_id."""
    coin_ids = [i.strip() for i in ids.split(",") if i.strip()][:50]
    return await coingecko.fetch_yearly_ranges(coin_ids)


@router.get("/supply")
async def get_supply(
    limit: int = Query(200, ge=1, le=250),
    _: User = Depends(get_current_user),
):
    """Supply data keyed by uppercase symbol — always from CoinGecko, never DB fallback."""
    raw = await coingecko.fetch_top_coins(limit)
    return {
        item["symbol"].upper(): {
            "circulating_supply": item.get("circulating_supply"),
            "max_supply":         item.get("max_supply"),
        }
        for item in raw
    }


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
