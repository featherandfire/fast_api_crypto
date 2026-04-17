"""Async CryptoCompare API client for long-range historical price data."""
import asyncio
import json
import logging
import math
import os
import time
from typing import List, Dict, Optional

import aiohttp

from app.config import settings

logger = logging.getLogger(__name__)

_BASE = settings.cryptocompare_base_url
_API_KEY = settings.cryptocompare_api_key

# ── Persistent disk + memory cache ───────────────────────────────────────────
_CACHE_FILE = os.path.join(os.path.dirname(__file__), "..", "cryptocompare_cache.json")
_change_cache: Dict[str, tuple] = {}   # "SYM:days" -> (fetched_at_epoch, pct_change)
_vol_cache: Dict[str, tuple] = {}      # "SYM:days" -> (fetched_at_epoch, annualized_vol)
_CHANGE_TTL = 86400                     # 24 hours
_VOL_TTL = 86400                        # 24 hours

# ── Background task state ────────────────────────────────────────────────────
_bg_task: Optional[asyncio.Task] = None
_DAYS_LIST = [548]                       # 1.5Y
_VOL_PERIODS = [90, 180, 365]            # 90-day, 180-day, and 1-year volatility


def _load_cache_from_disk():
    """Load persisted cache from JSON file into memory."""
    global _change_cache, _vol_cache
    try:
        with open(_CACHE_FILE, "r") as f:
            raw = json.load(f)
        now = time.time()
        changes = raw.get("changes", raw if "vol" not in raw else {})
        vols = raw.get("vol", {})
        loaded = 0
        for key, entry in changes.items():
            ts, pct = entry
            if now - ts < _CHANGE_TTL:
                _change_cache[key] = (time.monotonic() - (now - ts), pct)
                loaded += 1
        for key, entry in vols.items():
            ts, val = entry
            if now - ts < _VOL_TTL:
                _vol_cache[key] = (time.monotonic() - (now - ts), val)
                loaded += 1
        logger.info("Loaded %d entries from CryptoCompare disk cache", loaded)
    except FileNotFoundError:
        logger.info("No CryptoCompare disk cache found — will build from scratch")
    except Exception as e:
        logger.warning("Failed to load CryptoCompare disk cache: %s", e)


def _save_cache_to_disk():
    """Persist current cache to JSON file using wall-clock timestamps."""
    try:
        now_mono = time.monotonic()
        now_wall = time.time()
        changes = {}
        for key, (mono_ts, pct) in _change_cache.items():
            wall_ts = now_wall - (now_mono - mono_ts)
            changes[key] = [wall_ts, pct]
        vols = {}
        for key, (mono_ts, val) in _vol_cache.items():
            wall_ts = now_wall - (now_mono - mono_ts)
            vols[key] = [wall_ts, val]
        with open(_CACHE_FILE, "w") as f:
            json.dump({"changes": changes, "vol": vols}, f)
    except Exception as e:
        logger.warning("Failed to save CryptoCompare disk cache: %s", e)


async def _get(session: aiohttp.ClientSession, url: str, params: dict = None) -> dict:
    """GET with retry on rate limit."""
    headers = {}
    if _API_KEY:
        headers["authorization"] = f"Apikey {_API_KEY}"
    for attempt in range(3):
        async with session.get(
            url, params=params, headers=headers,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status == 429:
                if attempt < 2:
                    await asyncio.sleep(5 * (attempt + 1))
                    continue
                return {}
            resp.raise_for_status()
            data = await resp.json()
            if data.get("Response") == "Error":
                logger.debug("CryptoCompare: %s", data.get("Message", ""))
                return {}
            return data
    return {}


async def _fetch_one_symbol(session: aiohttp.ClientSession, sym: str, days: int) -> Optional[float]:
    """Fetch % change for a single symbol/days combo. Returns pct or None."""
    try:
        data = await _get(session, f"{_BASE}/data/v2/histoday", params={
            "fsym": sym,
            "tsym": "USD",
            "limit": days,
        })
        points = data.get("Data", {}).get("Data", [])
        if len(points) >= 2:
            old_price = points[0]["close"]
            new_price = points[-1]["close"]
            if old_price and old_price > 0:
                return round(((new_price - old_price) / old_price) * 100, 2)
    except Exception as e:
        logger.warning("CryptoCompare fetch failed for %s/%d days: %s", sym, days, e)
    return None


async def _fetch_volatility(session: aiohttp.ClientSession, sym: str, days: int = 90) -> Optional[float]:
    """Fetch annualized volatility for a symbol over N days. Returns float (e.g. 0.55) or None."""
    try:
        data = await _get(session, f"{_BASE}/data/v2/histoday", params={
            "fsym": sym,
            "tsym": "USD",
            "limit": days,
        })
        points = data.get("Data", {}).get("Data", [])
        closes = [p["close"] for p in points if p.get("close") and p["close"] > 0]
        if len(closes) < 10:
            return None
        # Daily returns
        returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]
        # Standard deviation of daily returns
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / len(returns)
        daily_std = math.sqrt(variance)
        # Annualize
        annualized = round(daily_std * math.sqrt(365), 4)
        return annualized
    except Exception as e:
        logger.warning("CryptoCompare volatility fetch failed for %s: %s", sym, e)
        return None


async def _background_prefetch():
    """Continuously pre-fetch long-range data for all top coins."""
    from app import coingecko

    while True:
        try:
            raw = await coingecko.fetch_top_coins(200)
            symbols = list({item["symbol"].upper() for item in raw if item.get("symbol")})
            now = time.monotonic()

            # Count how many actually need fetching
            stale = [(sym, days) for sym in symbols for days in _DAYS_LIST
                     if f"{sym}:{days}" not in _change_cache
                     or (now - _change_cache[f"{sym}:{days}"][0]) >= _CHANGE_TTL]

            if not stale:
                logger.info("CryptoCompare cache fully warm (%d entries), sleeping 24h", len(_change_cache))
            else:
                logger.info("CryptoCompare prefetch: %d stale of %d total, fetching...",
                            len(stale), len(symbols) * len(_DAYS_LIST))
                fetched = 0
                async with aiohttp.ClientSession() as session:
                    for sym, days in stale:
                        pct = await _fetch_one_symbol(session, sym, days)
                        _change_cache[f"{sym}:{days}"] = (time.monotonic(), pct)
                        fetched += 1
                        # Save to disk every 20 fetches so progress persists
                        if fetched % 20 == 0:
                            _save_cache_to_disk()
                        await asyncio.sleep(1.5)

                _save_cache_to_disk()
                logger.info("CryptoCompare change prefetch complete: %d fetched", fetched)

        except Exception as e:
            logger.error("CryptoCompare background prefetch error: %s", e)

        await asyncio.sleep(86400)


def start_background_prefetch():
    """Load disk cache, then launch the background prefetch task."""
    global _bg_task
    _load_cache_from_disk()
    if _bg_task is None or _bg_task.done():
        _bg_task = asyncio.create_task(_background_prefetch())
        logger.info("CryptoCompare background prefetch task started")


def stop_background_prefetch():
    """Cancel the background prefetch task and save cache."""
    global _bg_task
    _save_cache_to_disk()
    if _bg_task and not _bg_task.done():
        _bg_task.cancel()
        _bg_task = None


async def fetch_pct_changes(symbols: List[str], days_list: List[int]) -> Dict[str, Dict[int, Optional[float]]]:
    """
    Return {SYMBOL: {days: pct_change, ...}, ...}.
    Serves entirely from cache. No live API calls — background task handles fetching.
    """
    results: Dict[str, Dict[int, Optional[float]]] = {}
    now = time.monotonic()

    for sym in symbols:
        for days in days_list:
            cache_key = f"{sym}:{days}"
            cached = _change_cache.get(cache_key)
            if cached and (now - cached[0]) < _CHANGE_TTL:
                results.setdefault(sym, {})[days] = cached[1]

    return results


async def fetch_volatilities(symbols: List[str], days_list: List[int] = None) -> Dict[str, Dict[int, Optional[float]]]:
    """
    Return {SYMBOL: {days: annualized_vol, ...}, ...}.
    Serves entirely from cache. No live API calls — background task handles fetching.
    """
    if days_list is None:
        days_list = _VOL_PERIODS
    results: Dict[str, Dict[int, Optional[float]]] = {}
    now = time.monotonic()

    for sym in symbols:
        for days in days_list:
            cache_key = f"{sym}:{days}"
            cached = _vol_cache.get(cache_key)
            if cached and (now - cached[0]) < _VOL_TTL:
                results.setdefault(sym, {})[days] = cached[1]

    return results
