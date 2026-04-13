"""Paxos API routes."""
import logging

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, Query

from app import paxos
from app.auth import get_current_user
from app.config import settings
from app.models import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/paxos", tags=["paxos"])


def _check_configured():
    if not settings.paxos_client_id or not settings.paxos_client_secret:
        raise HTTPException(status_code=503, detail="Paxos API credentials not configured")


@router.get("/debug")
async def debug(_: User = Depends(get_current_user)):
    """Return raw Paxos /profiles response for debugging."""
    _check_configured()
    results = {"base_url": settings.paxos_base_url}
    for path in ("/identity/profiles", "/profiles", "/markets"):
        try:
            results[path] = await paxos._get(path)
        except aiohttp.ClientResponseError as e:
            results[path] = {"error": e.status, "message": e.message}
        except Exception as e:
            results[path] = {"error": str(e)}
    return results


@router.get("/balances")
async def get_balances(_: User = Depends(get_current_user)):
    _check_configured()
    if not settings.paxos_profile_id:
        raise HTTPException(status_code=503, detail="PAXOS_PROFILE_ID not configured")
    try:
        return await paxos.fetch_balances(settings.paxos_profile_id)
    except aiohttp.ClientResponseError as e:
        body = await e.response.text() if hasattr(e, 'response') and e.response else ''
        logger.error("Paxos balances HTTP %s: %s — body: %s", e.status, e.message, body)
        raise HTTPException(status_code=502, detail=f"Paxos error {e.status}: {e.message} — {body}")
    except Exception as e:
        logger.error("Paxos balances failed: %s", e, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Failed to fetch Paxos balances: {e}")


@router.get("/markets")
async def get_markets(_: User = Depends(get_current_user)):
    _check_configured()
    try:
        return await paxos.fetch_markets()
    except aiohttp.ClientResponseError as e:
        raise HTTPException(status_code=502, detail=f"Paxos error {e.status}: {e.message}")
    except Exception as e:
        logger.error("Paxos markets failed: %s", e)
        raise HTTPException(status_code=502, detail="Failed to fetch Paxos markets")


@router.get("/ticker")
async def get_ticker(
    market: str = Query(..., min_length=1, max_length=20),
    _: User = Depends(get_current_user),
):
    _check_configured()
    try:
        return await paxos.fetch_ticker(market.upper())
    except aiohttp.ClientResponseError as e:
        raise HTTPException(status_code=502, detail=f"Paxos error {e.status}: {e.message}")
    except Exception as e:
        logger.error("Paxos ticker failed for %s: %s", market, e)
        raise HTTPException(status_code=502, detail="Failed to fetch Paxos ticker")


@router.get("/prices")
async def get_prices(_: User = Depends(get_current_user)):
    """Fetch tickers for all available USD markets from Paxos."""
    _check_configured()
    import asyncio
    markets = await paxos.fetch_markets()
    usd_pairs = [m["market"] for m in markets if m.get("quote_asset") == "USD"]
    tickers = await asyncio.gather(
        *[paxos.fetch_ticker(pair) for pair in usd_pairs],
        return_exceptions=True,
    )
    results = []
    for pair, ticker in zip(usd_pairs, tickers):
        if isinstance(ticker, Exception):
            continue
        ticker["market"] = pair
        results.append(ticker)
    return results
