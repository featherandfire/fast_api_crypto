"""Async Etherscan API client for ETH + ERC-20 wallet balance fetching."""
import asyncio
import logging
from typing import List, Dict, Optional
import aiohttp

logger = logging.getLogger(__name__)

from app.config import settings

_BASE = settings.etherscan_base_url
_SEMAPHORE_SIZE = 5  # Etherscan free tier: 5 req/sec

# Sentinel address used to represent native ETH (not a real ERC-20 contract)
_ETH_SENTINEL = "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"


async def _get(session: aiohttp.ClientSession, sem: asyncio.Semaphore, params: dict) -> dict:
    params["chainid"] = 1  # Ethereum mainnet (V2 API requirement)
    if settings.etherscan_api_key:
        params["apikey"] = settings.etherscan_api_key
    async with sem:
        async with session.get(
            _BASE, params=params, timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            resp.raise_for_status()
            return await resp.json()


async def _fetch_eth_balance(
    session: aiohttp.ClientSession, sem: asyncio.Semaphore, address: str
) -> float:
    data = await _get(session, sem, {
        "module": "account",
        "action": "balance",
        "address": address,
        "tag": "latest",
    })
    if data.get("status") == "1":
        return int(data["result"]) / 1e18
    return 0.0


async def _fetch_token_contracts(
    session: aiohttp.ClientSession, sem: asyncio.Semaphore, address: str
) -> List[Dict]:
    """Return deduplicated list of ERC-20 token contract metadata from transfer history."""
    data = await _get(session, sem, {
        "module": "account",
        "action": "tokentx",
        "address": address,
        "startblock": 0,
        "endblock": 99999999,
        "sort": "desc",       # most recent first — catches recently-acquired tokens
        "page": 1,
        "offset": 1000,
    })

    if data.get("status") != "1" or not isinstance(data.get("result"), list):
        return []

    seen: Dict[str, Dict] = {}
    for tx in data["result"]:
        ca = tx["contractAddress"].lower()
        if ca not in seen:
            seen[ca] = {
                "contract_address": ca,
                "symbol": tx.get("tokenSymbol", ""),
                "name": tx.get("tokenName", ""),
                "decimals": int(tx.get("tokenDecimal", "18") or "18"),
            }
    return list(seen.values())


async def _fetch_token_balance(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    address: str,
    contract: Dict,
) -> Optional[Dict]:
    """Fetch current balance for a single ERC-20 token. Returns None on any error."""
    try:
        data = await _get(session, sem, {
            "module": "account",
            "action": "tokenbalance",
            "contractaddress": contract["contract_address"],
            "address": address,
            "tag": "latest",
        })
        if data.get("status") == "1":
            raw = int(data["result"])
            decimals = contract["decimals"]
            balance = raw / (10 ** decimals) if decimals >= 0 else raw
            if balance > 0:
                return {**contract, "balance": balance}
    except (aiohttp.ClientError, KeyError, ValueError) as exc:
        logger.warning("Failed to fetch token balance for contract %s: %s", contract.get("contract_address"), exc)
    return None


async def fetch_wallet_balances(address: str) -> List[Dict]:
    """
    Fetch all non-zero balances for an Ethereum address.
    Returns a list of dicts:
      {contract_address, symbol, name, decimals, balance}
    ETH itself uses the sentinel contract address 0xeeee...
    Raises on hard Etherscan failure (ETH balance call).
    """
    sem = asyncio.Semaphore(_SEMAPHORE_SIZE)

    async with aiohttp.ClientSession() as session:
        # Fetch ETH balance and token contract list concurrently
        eth_balance, contracts = await asyncio.gather(
            _fetch_eth_balance(session, sem, address),
            _fetch_token_contracts(session, sem, address),
        )

        # Fetch all ERC-20 balances concurrently (semaphore limits concurrency)
        token_results = await asyncio.gather(
            *[_fetch_token_balance(session, sem, address, c) for c in contracts],
            return_exceptions=True,
        )

    balances: List[Dict] = []

    # Native ETH
    if eth_balance > 0:
        balances.append({
            "contract_address": _ETH_SENTINEL,
            "symbol": "ETH",
            "name": "Ethereum",
            "decimals": 18,
            "balance": eth_balance,
        })

    # ERC-20 tokens
    for result in token_results:
        if result and not isinstance(result, Exception):
            balances.append(result)

    return balances
