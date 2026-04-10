"""Blockchain hash/address lookup — detects chain by format + live RPC probing."""
import re
import asyncio
from typing import List, Optional, Literal

import aiohttp
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import get_current_user
from app.models import User
from app import solana_rpc

router = APIRouter(prefix="/api/lookup", tags=["lookup"])

# ── Chain config ──────────────────────────────────────────────────────────────

EVM_CHAINS = [
    {
        "chain": "ethereum",
        "chain_name": "Ethereum",
        "color": "#627EEA",
        "rpc_url": "https://cloudflare-eth.com",
        "explorer_base": "https://etherscan.io",
        "tx_path": "/tx/{hash}",
        "address_path": "/address/{hash}",
        "block_path": "/block/{hash}",
        "probe": True,
    },
    {
        "chain": "bsc",
        "chain_name": "BNB Smart Chain",
        "color": "#F3BA2F",
        "rpc_url": "https://bsc-dataseed.binance.org",
        "explorer_base": "https://bscscan.com",
        "tx_path": "/tx/{hash}",
        "address_path": "/address/{hash}",
        "block_path": "/block/{hash}",
        "probe": True,
    },
    {
        "chain": "polygon",
        "chain_name": "Polygon",
        "color": "#8247E5",
        "rpc_url": "https://polygon-rpc.com",
        "explorer_base": "https://polygonscan.com",
        "tx_path": "/tx/{hash}",
        "address_path": "/address/{hash}",
        "block_path": "/block/{hash}",
        "probe": True,
    },
    {
        "chain": "arbitrum",
        "chain_name": "Arbitrum One",
        "color": "#28A0F0",
        "rpc_url": "https://arb1.arbitrum.io/rpc",
        "explorer_base": "https://arbiscan.io",
        "tx_path": "/tx/{hash}",
        "address_path": "/address/{hash}",
        "block_path": "/block/{hash}",
        "probe": False,
    },
    {
        "chain": "optimism",
        "chain_name": "Optimism",
        "color": "#FF0420",
        "rpc_url": "https://mainnet.optimism.io",
        "explorer_base": "https://optimistic.etherscan.io",
        "tx_path": "/tx/{hash}",
        "address_path": "/address/{hash}",
        "block_path": "/block/{hash}",
        "probe": False,
    },
    {
        "chain": "avalanche",
        "chain_name": "Avalanche C-Chain",
        "color": "#E84142",
        "rpc_url": "https://api.avax.network/ext/bc/C/rpc",
        "explorer_base": "https://snowtrace.io",
        "tx_path": "/tx/{hash}",
        "address_path": "/address/{hash}",
        "block_path": "/block/{hash}",
        "probe": False,
    },
    {
        "chain": "base",
        "chain_name": "Base",
        "color": "#0052FF",
        "rpc_url": "https://mainnet.base.org",
        "explorer_base": "https://basescan.org",
        "tx_path": "/tx/{hash}",
        "address_path": "/address/{hash}",
        "block_path": "/block/{hash}",
        "probe": False,
    },
]

NON_EVM_CHAINS = {
    "bitcoin": {
        "chain": "bitcoin",
        "chain_name": "Bitcoin",
        "color": "#F7931A",
        "explorer_base": "https://mempool.space",
        "tx_path": "/tx/{hash}",
        "address_path": "/address/{hash}",
    },
    "solana": {
        "chain": "solana",
        "chain_name": "Solana",
        "color": "#9945FF",
        "explorer_base": "https://solscan.io",
        "tx_path": "/tx/{hash}",
        "address_path": "/account/{hash}",
    },
    "tron": {
        "chain": "tron",
        "chain_name": "Tron",
        "color": "#EF0027",
        "explorer_base": "https://tronscan.org",
        "tx_path": "/#/transaction/{hash}",
        "address_path": "/#/address/{hash}",
    },
    "litecoin": {
        "chain": "litecoin",
        "chain_name": "Litecoin",
        "color": "#BFBBBB",
        "explorer_base": "https://blockchair.com/litecoin",
        "tx_path": "/transaction/{hash}",
        "address_path": "/address/{hash}",
    },
}

# ── Compiled regexes ──────────────────────────────────────────────────────────

_RE_EVM_ADDRESS  = re.compile(r'^0x[0-9a-fA-F]{40}$')
_RE_EVM_TX       = re.compile(r'^0x[0-9a-fA-F]{64}$')
_RE_BTC_LEGACY   = re.compile(r'^[13][a-km-zA-HJ-NP-Z1-9]{24,33}$')
_RE_BTC_BECH32   = re.compile(r'^bc1[a-z0-9]{6,87}$')
_RE_HEX64        = re.compile(r'^[0-9a-fA-F]{64}$')
_RE_SOL_ADDRESS  = re.compile(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$')
_RE_SOL_SIG      = re.compile(r'^[1-9A-HJ-NP-Za-km-z]{87,88}$')
_RE_TRON         = re.compile(r'^T[1-9A-HJ-NP-Za-km-z]{33}$')
_RE_LTC_LEGACY   = re.compile(r'^[LM][a-km-zA-HJ-NP-Z1-9]{25,33}$')
_RE_LTC_BECH32   = re.compile(r'^ltc1[a-z0-9]{6,87}$')

# ── Schemas ───────────────────────────────────────────────────────────────────

class ChainMatch(BaseModel):
    chain: str
    chain_name: str
    color: str
    explorer_url: str
    explorer_link: str
    confidence: Literal["confirmed", "likely", "format_only"]


class TxSummary(BaseModel):
    # Universal
    chain: str = "Solana"
    status: str = "success"
    block_time: Optional[int] = None
    from_addr: str
    from_addr_short: str
    to_addr: str
    to_addr_short: str
    value: Optional[str] = None
    fee_sol: Optional[str] = None
    # Solana extras
    payer: str
    payer_short: str
    router: Optional[str] = None
    fee_display: Optional[str] = None


class LookupResponse(BaseModel):
    hash: str
    type: str
    matches: List[ChainMatch]
    summary: Optional[TxSummary] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _link(cfg: dict, hash_str: str, path_key: str) -> str:
    return cfg["explorer_base"] + cfg[path_key].format(hash=hash_str)


def _evm_match(cfg: dict, hash_str: str, path_key: str, confidence: str) -> ChainMatch:
    return ChainMatch(
        chain=cfg["chain"],
        chain_name=cfg["chain_name"],
        color=cfg["color"],
        explorer_url=cfg["explorer_base"],
        explorer_link=_link(cfg, hash_str, path_key),
        confidence=confidence,
    )


def _non_evm_match(key: str, hash_str: str, path_key: str, confidence: str) -> ChainMatch:
    cfg = NON_EVM_CHAINS[key]
    return ChainMatch(
        chain=cfg["chain"],
        chain_name=cfg["chain_name"],
        color=cfg["color"],
        explorer_url=cfg["explorer_base"],
        explorer_link=_link(cfg, hash_str, path_key),
        confidence=confidence,
    )


# ── Format detection ──────────────────────────────────────────────────────────

def detect_hash_format(h: str) -> dict:
    """Returns detection metadata dict. Uses lowercased copy for regex only."""
    hl = h.lower()

    if _RE_EVM_ADDRESS.match(h):
        return {"raw_type": "evm_address", "display_type": "EVM Address"}

    if _RE_EVM_TX.match(hl):
        return {"raw_type": "evm_tx_hash", "display_type": "EVM Transaction / Block Hash"}

    if _RE_TRON.match(h):
        return {"raw_type": "tron_address", "display_type": "Tron Address"}

    if _RE_LTC_BECH32.match(hl):
        return {"raw_type": "ltc_bech32_address", "display_type": "Litecoin Address (Bech32)"}

    if _RE_LTC_LEGACY.match(h):
        return {"raw_type": "ltc_address", "display_type": "Litecoin Address"}

    if _RE_BTC_BECH32.match(hl):
        return {"raw_type": "btc_bech32_address", "display_type": "Bitcoin Address (SegWit/Taproot)"}

    if _RE_BTC_LEGACY.match(h):
        return {"raw_type": "btc_address", "display_type": "Bitcoin Address"}

    if _RE_SOL_SIG.match(h):
        return {"raw_type": "sol_tx_sig", "display_type": "Solana Transaction Signature"}

    if _RE_HEX64.match(hl):
        return {"raw_type": "btc_tx_hash", "display_type": "Bitcoin Transaction Hash"}

    if _RE_SOL_ADDRESS.match(h):
        return {"raw_type": "sol_address", "display_type": "Solana Address"}

    return {"raw_type": "unknown", "display_type": "Unknown Format"}


# ── EVM RPC probing ───────────────────────────────────────────────────────────

async def _probe_one(
    session: aiohttp.ClientSession,
    chain_cfg: dict,
    hash_str: str,
) -> Optional[str]:
    """Returns chain id string if tx found, None if not found, raises on network error."""
    payload = {
        "jsonrpc": "2.0", "id": 1,
        "method": "eth_getTransactionByHash",
        "params": [hash_str],
    }
    async with session.post(
        chain_cfg["rpc_url"],
        json=payload,
        timeout=aiohttp.ClientTimeout(total=3),
    ) as resp:
        data = await resp.json(content_type=None)
    if data.get("result") is not None:
        return chain_cfg["chain"]
    return None


async def _probe_evm_chains(hash_str: str) -> dict:
    """
    Probe ETH, BSC, Polygon concurrently.
    Returns {"confirmed": [...chain ids], "all_failed": bool}
    """
    probe_chains = [c for c in EVM_CHAINS if c["probe"]]
    confirmed = []
    all_failed = True

    async with aiohttp.ClientSession() as session:
        results = await asyncio.gather(
            *[_probe_one(session, c, hash_str) for c in probe_chains],
            return_exceptions=True,
        )

    for result in results:
        if isinstance(result, Exception):
            continue  # probe failed (timeout, network)
        all_failed = False
        if result is not None:
            confirmed.append(result)

    return {"confirmed": confirmed, "all_failed": all_failed}


# ── Route handler ─────────────────────────────────────────────────────────────

@router.get("/{hash_str}", response_model=LookupResponse)
async def lookup_hash(
    hash_str: str,
    _: User = Depends(get_current_user),
):
    h = hash_str.strip()
    if not h:
        raise HTTPException(status_code=422, detail="Empty input")
    if len(h) > 200:
        raise HTTPException(status_code=422, detail="Input too long")

    detection = detect_hash_format(h)
    raw_type = detection["raw_type"]
    matches: List[ChainMatch] = []
    summary: Optional[TxSummary] = None

    if raw_type == "unknown":
        return LookupResponse(hash=h, type=detection["display_type"], matches=[])

    # ── EVM address — all EVM chains share the same address format ────────────
    if raw_type == "evm_address":
        for cfg in EVM_CHAINS:
            matches.append(_evm_match(cfg, h, "address_path", "format_only"))

    # ── EVM tx / block hash — probe top 3, others as "likely" ────────────────
    elif raw_type == "evm_tx_hash":
        probe_result = await _probe_evm_chains(h)
        confirmed_ids = set(probe_result["confirmed"])
        all_failed = probe_result["all_failed"]

        if confirmed_ids:
            # Add confirmed chains first
            for cfg in EVM_CHAINS:
                if cfg["chain"] in confirmed_ids:
                    matches.append(_evm_match(cfg, h, "tx_path", "confirmed"))
            # Non-probed EVM chains as "likely" (valid EVM tx could exist on any EVM chain)
            for cfg in EVM_CHAINS:
                if not cfg["probe"]:
                    matches.append(_evm_match(cfg, h, "tx_path", "likely"))
        elif all_failed:
            # Network down — give format_only links for all EVM chains
            for cfg in EVM_CHAINS:
                matches.append(_evm_match(cfg, h, "tx_path", "format_only"))
        # else: probes succeeded but tx not found — return empty matches

    # ── Bitcoin ───────────────────────────────────────────────────────────────
    elif raw_type in ("btc_address", "btc_bech32_address"):
        matches.append(_non_evm_match("bitcoin", h, "address_path", "likely"))

    elif raw_type == "btc_tx_hash":
        matches.append(_non_evm_match("bitcoin", h, "tx_path", "likely"))

    # ── Solana ────────────────────────────────────────────────────────────────
    elif raw_type == "sol_address":
        matches.append(_non_evm_match("solana", h, "address_path", "likely"))

    elif raw_type == "sol_tx_sig":
        matches.append(_non_evm_match("solana", h, "tx_path", "likely"))
        raw_summary = await solana_rpc.fetch_tx_summary(h)
        if raw_summary:
            summary = TxSummary(**raw_summary)

    # ── Tron ──────────────────────────────────────────────────────────────────
    elif raw_type == "tron_address":
        matches.append(_non_evm_match("tron", h, "address_path", "likely"))

    # ── Litecoin ──────────────────────────────────────────────────────────────
    elif raw_type in ("ltc_address", "ltc_bech32_address"):
        matches.append(_non_evm_match("litecoin", h, "address_path", "likely"))

    return LookupResponse(hash=h, type=detection["display_type"], matches=matches, summary=summary)
