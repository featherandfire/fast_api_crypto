"""Async CoinGecko API client with concurrent fetching."""
import asyncio
import logging
import time
from typing import List, Dict, Any, Optional
import aiohttp

logger = logging.getLogger(__name__)

from app.config import settings

_BASE = settings.coingecko_base_url

# ── Simple in-memory TTL caches ──────────────────────────────────────────────
_history_cache: Dict[str, tuple] = {}   # key -> (fetched_at, data)
_HISTORY_TTL = 300                       # 5 minutes

_top_cache: Dict[int, tuple] = {}        # limit -> (fetched_at, data)
_TOP_TTL = 120                           # 2 minutes


async def _get(session: aiohttp.ClientSession, url: str, params: dict = None) -> Any:
    """GET with up to 3 retries on 429 (exponential backoff)."""
    backoff = 1.5
    for attempt in range(3):
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 429:
                if attempt < 2:
                    await asyncio.sleep(backoff * (2 ** attempt))
                    continue
                resp.raise_for_status()
            resp.raise_for_status()
            return await resp.json()


async def fetch_prices(coin_ids: List[str]) -> Dict[str, Dict]:
    """Fetch current prices for multiple coins concurrently in batches of 50."""
    if not coin_ids:
        return {}

    batch_size = 50
    results: Dict[str, Dict] = {}

    async with aiohttp.ClientSession() as session:
        batches = [coin_ids[i:i + batch_size] for i in range(0, len(coin_ids), batch_size)]

        async def fetch_batch(ids: List[str]) -> Dict:
            return await _get(session, f"{_BASE}/coins/markets", params={
                "vs_currency": "usd",
                "ids": ",".join(ids),
                "order": "market_cap_desc",
                "per_page": len(ids),
                "page": 1,
                "sparkline": "false",
                "price_change_percentage": "24h",
            })

        batch_results = await asyncio.gather(*[fetch_batch(b) for b in batches], return_exceptions=True)

        for batch_data in batch_results:
            if isinstance(batch_data, Exception):
                continue
            for coin in batch_data:
                results[coin["id"]] = {
                    "coingecko_id": coin["id"],
                    "symbol": coin["symbol"],
                    "name": coin["name"],
                    "current_price_usd": coin.get("current_price"),
                    "price_change_24h": coin.get("price_change_percentage_24h"),
                    "market_cap": coin.get("market_cap"),
                    "image_url": coin.get("image"),
                }

    return results


async def fetch_price_history(coin_id: str, days: int = 30) -> List[List]:
    """Return [[timestamp_ms, price], ...] for the given coin."""
    cache_key = f"{coin_id}:{days}"
    cached = _history_cache.get(cache_key)
    if cached and (time.monotonic() - cached[0]) < _HISTORY_TTL:
        return cached[1]

    async with aiohttp.ClientSession() as session:
        data = await _get(session, f"{_BASE}/coins/{coin_id}/market_chart", params={
            "vs_currency": "usd",
            "days": days,
        })
    prices = data.get("prices", [])
    _history_cache[cache_key] = (time.monotonic(), prices)
    return prices


async def search_coins(query: str) -> List[Dict]:
    """Search CoinGecko for coins by name/symbol."""
    async with aiohttp.ClientSession() as session:
        data = await _get(session, f"{_BASE}/search", params={"query": query})
    coins = data.get("coins", [])[:20]
    return [{"id": c["id"], "name": c["name"], "symbol": c["symbol"], "thumb": c.get("thumb")} for c in coins]


async def match_tokens_by_contract(contract_addresses: List[str]) -> Dict[str, Dict]:
    """
    Look up CoinGecko metadata for a list of Ethereum contract addresses.
    Returns {contract_address_lower -> {coingecko_id, name, symbol, current_price_usd, image_url}}.
    Addresses with no CoinGecko match are silently omitted.
    """
    if not contract_addresses:
        return {}

    sem = asyncio.Semaphore(3)  # conservative — free tier ~30 req/min

    async def fetch_one(session: aiohttp.ClientSession, address: str) -> Optional[tuple]:
        try:
            async with sem:
                async with session.get(
                    f"{_BASE}/coins/ethereum/contract/{address}",
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 404:
                        return None
                    if resp.status == 429:
                        return None  # rate limited — skip silently
                    resp.raise_for_status()
                    data = await resp.json()
            return (address.lower(), {
                "coingecko_id": data["id"],
                "name": data["name"],
                "symbol": data["symbol"],
                "current_price_usd": (data.get("market_data") or {}).get("current_price", {}).get("usd"),
                "image_url": (data.get("image") or {}).get("small"),
            })
        except aiohttp.ClientError as exc:
            logger.warning("Contract lookup failed for %s: %s", address, exc)
            return None

    async with aiohttp.ClientSession() as session:
        results = await asyncio.gather(
            *[fetch_one(session, addr) for addr in contract_addresses],
            return_exceptions=True,
        )

    return {addr: info for r in results if r and not isinstance(r, Exception) for addr, info in [r]}


async def fetch_top_coins(limit: int = 50) -> List[Dict]:
    """Fetch top N coins by market cap, cached for 60 s."""
    cached = _top_cache.get(limit)
    if cached and (time.monotonic() - cached[0]) < _TOP_TTL:
        return cached[1]

    async with aiohttp.ClientSession() as session:
        data = await _get(session, f"{_BASE}/coins/markets", params={
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": limit,
            "page": 1,
            "sparkline": "false",
            "price_change_percentage": "24h",
        })
    _top_cache[limit] = (time.monotonic(), data)
    return data
