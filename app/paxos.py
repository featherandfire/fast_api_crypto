"""Paxos API client — OAuth2 client-credentials + REST calls."""
import asyncio
import logging
import time
from typing import Any, Dict, Optional

import aiohttp

from app.config import settings

logger = logging.getLogger(__name__)

# ── Token cache ───────────────────────────────────────────────────────────────

_token_cache: Dict[str, Any] = {}
_token_lock = asyncio.Lock()


async def _get_token() -> str:
    """Fetch (or return cached) OAuth2 access token — concurrency-safe."""
    now = time.monotonic()
    if _token_cache.get("token") and _token_cache.get("expires_at", 0) > now + 30:
        return _token_cache["token"]

    async with _token_lock:
        # Re-check after acquiring lock in case another coroutine just fetched
        now = time.monotonic()
        if _token_cache.get("token") and _token_cache.get("expires_at", 0) > now + 30:
            return _token_cache["token"]

        async with aiohttp.ClientSession() as session:
            async with session.post(
                settings.paxos_oauth_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": settings.paxos_client_id,
                    "client_secret": settings.paxos_client_secret,
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()

        _token_cache["token"] = data["access_token"]
        _token_cache["expires_at"] = now + data.get("expires_in", 3600)
        logger.error("Paxos token acquired, scope: %s", data.get("scope", "unknown"))
        return _token_cache["token"]


async def _get(path: str, params: Optional[dict] = None) -> Any:
    token = await _get_token()
    url = f"{settings.paxos_base_url}{path}"
    logger.debug("Paxos GET %s", url)
    async with aiohttp.ClientSession() as session:
        async with session.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()


# ── Public helpers ────────────────────────────────────────────────────────────

async def fetch_balances(profile_id: str) -> list:
    """Return list of asset balances for a profile."""
    logger.error("Fetching balances for profile_id=%r", profile_id)
    data = await _get(f"/profiles/{profile_id}/balances")
    return data.get("items", data) if isinstance(data, dict) else data


async def fetch_markets() -> list:
    """Return available trading markets."""
    data = await _get("/markets")
    return data.get("markets", data) if isinstance(data, dict) else data


async def fetch_ticker(market: str) -> dict:
    """Return latest ticker for a market (e.g. 'BTCUSD')."""
    return await _get(f"/markets/{market}/ticker")
