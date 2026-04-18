"""Async CoinGecko API client with concurrent fetching."""
import asyncio
import json
import logging
import math
import os
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
_TOP_TTL = 300                           # 5 minutes


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


_YEARLY_CACHE_FILE = os.path.join(os.path.dirname(__file__), "..", "coingecko_yearly_cache.json")
_yearly_cache: Dict[str, tuple] = {}   # coin_id -> (fetched_at, {high, low, vol_*})
_YEARLY_TTL = 86400                     # 24 hours


def _load_yearly_cache():
    """Load yearly cache from disk."""
    global _yearly_cache
    try:
        with open(_YEARLY_CACHE_FILE, "r") as f:
            raw = json.load(f)
        now = time.time()
        loaded = 0
        for key, entry in raw.items():
            ts, data = entry
            if now - ts < _YEARLY_TTL:
                _yearly_cache[key] = (time.monotonic() - (now - ts), data)
                loaded += 1
        logger.info("Loaded %d entries from CoinGecko yearly disk cache", loaded)
    except FileNotFoundError:
        logger.info("No CoinGecko yearly disk cache found — will build from API")
    except Exception as e:
        logger.warning("Failed to load CoinGecko yearly disk cache: %s", e)


def _save_yearly_cache():
    """Persist yearly cache to disk."""
    try:
        now_mono = time.monotonic()
        now_wall = time.time()
        serializable = {}
        for key, (mono_ts, data) in _yearly_cache.items():
            wall_ts = now_wall - (now_mono - mono_ts)
            serializable[key] = [wall_ts, data]
        with open(_YEARLY_CACHE_FILE, "w") as f:
            json.dump(serializable, f)
    except Exception as e:
        logger.warning("Failed to save CoinGecko yearly disk cache: %s", e)


def _calc_volatility(prices: List[float], tail_n: int) -> Optional[float]:
    """Annualized volatility from the last tail_n daily prices."""
    pts = prices[-tail_n:] if len(prices) >= tail_n else prices
    if len(pts) < 10:
        return None
    returns = [(pts[i] - pts[i - 1]) / pts[i - 1] for i in range(1, len(pts)) if pts[i - 1] > 0]
    if len(returns) < 5:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / len(returns)
    return round(math.sqrt(variance) * math.sqrt(365), 4)


async def _fetch_one_yearly(session: aiohttp.ClientSession, coin_id: str) -> Optional[Dict]:
    """Fetch yearly data for a single coin. Returns result dict or None."""
    try:
        data = await _get(session, f"{_BASE}/coins/{coin_id}/market_chart", params={
            "vs_currency": "usd",
            "days": 365,
        })
        prices = [p[1] for p in data.get("prices", [])]
        if not prices:
            return None
        return {
            "high_1y":   max(prices),
            "low_1y":    min(prices),
            "vol_90d":   _calc_volatility(prices, 90),
            "vol_180d":  _calc_volatility(prices, 180),
            "vol_365d":  _calc_volatility(prices, 365),
        }
    except Exception as e:
        logger.debug("CoinGecko yearly fetch failed for %s: %s", coin_id, e)
        return None


# ── Background prefetch task ─────────────────────────────────────────────────
_yearly_bg_task: Optional[asyncio.Task] = None


async def _yearly_background_prefetch():
    """Continuously pre-fetch yearly data for all top coins at a safe pace."""
    # Wait for the server to fully start and initial /coins/top to settle
    await asyncio.sleep(10)

    while True:
        try:
            raw = await fetch_top_coins(200)
            coin_ids = [item["id"] for item in raw if item.get("id")]
            now = time.monotonic()

            stale = [cid for cid in coin_ids
                     if cid not in _yearly_cache
                     or (now - _yearly_cache[cid][0]) >= _YEARLY_TTL]

            if not stale:
                logger.info("CoinGecko yearly cache fully warm (%d entries), sleeping 24h", len(_yearly_cache))
                await asyncio.sleep(86400)
            else:
                logger.info("CoinGecko yearly prefetch: %d stale of %d total", len(stale), len(coin_ids))
                fetched = 0
                async with aiohttp.ClientSession() as session:
                    for coin_id in stale:
                        result = await _fetch_one_yearly(session, coin_id)
                        _yearly_cache[coin_id] = (time.monotonic(), result or {})
                        fetched += 1
                        if fetched % 10 == 0:
                            _save_yearly_cache()
                        # ~3s per request = ~20 req/min, safe for free tier
                        await asyncio.sleep(3)

                _save_yearly_cache()
                logger.info("CoinGecko yearly prefetch complete: %d fetched", fetched)
                await asyncio.sleep(86400)
        except Exception as e:
            logger.error("CoinGecko yearly background prefetch error: %s — retrying in 5 min", e)
            await asyncio.sleep(300)


def start_yearly_prefetch():
    """Launch the yearly background prefetch task."""
    global _yearly_bg_task
    if _yearly_bg_task is None or _yearly_bg_task.done():
        _yearly_bg_task = asyncio.create_task(_yearly_background_prefetch())
        logger.info("CoinGecko yearly background prefetch task started")


def stop_yearly_prefetch():
    """Cancel the yearly background prefetch task and save cache."""
    global _yearly_bg_task
    _save_yearly_cache()
    if _yearly_bg_task and not _yearly_bg_task.done():
        _yearly_bg_task.cancel()
        _yearly_bg_task = None


async def fetch_yearly_ranges(coin_ids: List[str]) -> Dict[str, Dict]:
    """Serve yearly data from cache only. Background task handles fetching."""
    now = time.monotonic()
    results = {}
    for coin_id in coin_ids:
        cached = _yearly_cache.get(coin_id)
        if cached and (now - cached[0]) < _YEARLY_TTL and cached[1]:
            results[coin_id] = cached[1]
    return results


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
            "price_change_percentage": "24h,200d,1y",
        })
    _top_cache[limit] = (time.monotonic(), data)
    return data
