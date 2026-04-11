"""Solana RPC client — fetches and parses transaction summaries."""
import logging
from typing import Optional, List, Dict, Tuple
import aiohttp

logger = logging.getLogger(__name__)

_RPC = "https://api.mainnet-beta.solana.com"

# ── Known token mints ─────────────────────────────────────────────────────────

_KNOWN_MINTS: Dict[str, str] = {
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "USDT",
    "So11111111111111111111111111111111111111112":   "wSOL",
    "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263": "BONK",
    "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN":  "JUP",
    "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R": "RAY",
    "orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE":  "ORCA",
    "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So":  "mSOL",
    "7dHbWXmci3dT8UFYWYZweBLXgycu7Y3iL6trKn1Y7ARj":  "stSOL",
    "HZ1JovNiVvGrGs7igeECtKiGHCFwHd9YTFGMCdFMkiuQ":  "PYTH",
    "7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs":  "wETH",
    "9n4nbM75f5Ui33ZbPYXn59EwSgE8CGsHtAeTH5YFeJ9E":   "wBTC",
    "MangoCzJ36AjZyKwVj3VnYU4GTonjfVEnJmvvWaxLac":   "MNGO",
}

_STABLECOINS = {
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
}

# ── Known DEX / router program IDs ────────────────────────────────────────────

_ROUTERS: Dict[str, str] = {
    "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4": "Jupiter",
    "JUP4Fb2cqiRUcaTHdrPC8h2gNsA2ETXiPDD33WcGuJB":  "Jupiter v4",
    "JUP3c2Uh3WA4Ng34tw6kPd2G4XKbb5zvxLd4m1K9yXa":  "Jupiter v3",
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8": "Raydium AMM",
    "5quBtoiQqxF9Jv6KYKctB59NT3gtJD2Y65kdnB1Uev3h":  "Raydium CLMM",
    "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK":  "Raydium CAMM",
    "9W959DqEETiGZocYWCQPaJ6sBmUzgfxXfqGeTEdp3aQP":  "Orca",
    "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc":   "Orca Whirlpools",
    "srmqPvymJeFKQ4zGQed1GFppgkRHL9kaELCbyksJtPX":   "OpenBook",
    "opnb2LAfJYbRMAHHvqjCwQxanZn7ReEHp1k81EohpZb":   "OpenBook v2",
    "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P":   "Pump.fun",
    "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo":   "Meteora DLMM",
    "Eo7WjKq67rjJQSZxS6z3YkapzY3eMj6Xy8X5EkAW7vA":   "Meteora",
    "PhoeNiXZ8ByJGLkxNfZRnkUfjvmuYqLR89jjFHGqdXY":   "Phoenix",
    "DEXYosS6oEGvk8uCDayvwEZz4qEyDJRf9nFgYCaqPMTm":  "Dex.guru",
    "HKx5d1sMEmBaT17a1r5tCqKw95JZt7M1LRJvkxvfFaV4":  "OKX DEX",
    "6MLxLqofvEkLnefa3cR6jR4H7qCVHXxU1WuwwCzBbfZq":  "OKX DEX",
    "obriQD1zbpyLz95G5n7nJe6a4DPjpFwa5XYPoNm113y":   "OKX DEX",
}

_MIN_CHANGE = 1e-9


# ── Helpers ───────────────────────────────────────────────────────────────────

def _shorten(addr: str) -> str:
    return f"{addr[:6]}...{addr[-4:]}"


def _symbol(mint: str) -> str:
    return _KNOWN_MINTS.get(mint, _shorten(mint))


def _fmt_amount(amount: float) -> str:
    """Format a token amount with full precision — no rounding, no scientific notation."""
    formatted = f"{amount:,.9f}".rstrip("0").rstrip(".")
    return formatted


def _detect_router(account_keys: list) -> Optional[str]:
    """Return the first recognized DEX program found in the transaction's account keys."""
    for key in account_keys:
        pubkey = key.get("pubkey", "")
        if pubkey in _ROUTERS:
            return _ROUTERS[pubkey]
    return None


# ── Core parser ───────────────────────────────────────────────────────────────

def _parse_summary(tx: dict) -> Optional[dict]:
    try:
        meta = tx.get("meta") or {}
        msg  = tx["transaction"]["message"]
        keys = msg["accountKeys"]

        payer = keys[0]["pubkey"]
        fee   = (meta.get("fee") or 0) / 1e9

        # ── Native SOL change for the payer (net of tx fee) ───────────────────
        pre_bals  = meta.get("preBalances")  or []
        post_bals = meta.get("postBalances") or []
        sol_sent = sol_received = 0.0
        if pre_bals and post_bals:
            net_sol = (post_bals[0] - pre_bals[0]) / 1e9 + fee
            if net_sol < -_MIN_CHANGE:
                sol_sent = abs(net_sol)
            elif net_sol > _MIN_CHANGE:
                sol_received = net_sol

        # ── Build token balance index ─────────────────────────────────────────
        pre_tok  = {e["accountIndex"]: e for e in (meta.get("preTokenBalances")  or [])}
        post_tok = {e["accountIndex"]: e for e in (meta.get("postTokenBalances") or [])}
        all_idx  = set(pre_tok) | set(post_tok)

        def _token_changes_for(actor: str) -> Tuple[List[dict], List[dict]]:
            """Return (sent_items, received_items) for a given owner pubkey."""
            sent: List[dict] = []
            recv: List[dict] = []
            for i in all_idx:
                pe = pre_tok.get(i)
                po = post_tok.get(i)
                if (po or pe or {}).get("owner") != actor:
                    continue
                mint    = (po or pe)["mint"]
                pre_a   = float((pe or {}).get("uiTokenAmount", {}).get("uiAmount") or 0)
                post_a  = float((po or {}).get("uiTokenAmount", {}).get("uiAmount") or 0)
                delta   = post_a - pre_a
                sym     = _symbol(mint)
                if delta < -_MIN_CHANGE:
                    sent.append({"mint": mint, "symbol": sym, "amount": abs(delta)})
                elif delta > _MIN_CHANGE:
                    recv.append({"mint": mint, "symbol": sym, "amount": delta})
            return sent, recv

        # Primary: payer-owned token changes
        sent_items, received_items = _token_changes_for(payer)

        # Fallback: if payer has no token flows (e.g. Jito bundle / routing tx),
        # find the first other signer that does.
        actor = payer
        if not sent_items and not received_items:
            for key in keys[1:]:
                if not key.get("signer"):
                    continue
                candidate = key["pubkey"]
                s, r = _token_changes_for(candidate)
                if s or r:
                    sent_items, received_items = s, r
                    actor = candidate
                    break

        # ── Detect router ─────────────────────────────────────────────────────
        router = _detect_router(keys)

        # ── Fee detection ─────────────────────────────────────────────────────
        # Non-payer accounts that gained the same mint as what payer received =
        # platform / router fee accounts.
        fee_display: Optional[str] = None

        if received_items:
            recv_mint   = received_items[0]["mint"]
            recv_amount = received_items[0]["amount"]
            fee_gained  = 0.0

            for idx in all_idx:
                pe = pre_tok.get(idx)
                po = post_tok.get(idx)
                owner = (po or pe or {}).get("owner")
                if owner == actor:
                    continue
                mint     = (po or pe or {}).get("mint", "")
                if mint != recv_mint:
                    continue
                pre_amt  = float((pe or {}).get("uiTokenAmount", {}).get("uiAmount") or 0)
                post_amt = float((po or {}).get("uiTokenAmount", {}).get("uiAmount") or 0)
                delta    = post_amt - pre_amt
                if delta > _MIN_CHANGE:
                    fee_gained += delta

            if fee_gained > _MIN_CHANGE:
                total     = recv_amount + fee_gained
                fee_pct   = (fee_gained / total * 100) if total > 0 else None
                recv_sym  = received_items[0]["symbol"]
                if recv_mint in _STABLECOINS:
                    fee_str = f"${fee_gained:.2f}"
                else:
                    fee_str = f"{_fmt_amount(fee_gained)} {recv_sym}"
                if fee_pct is not None:
                    fee_display = f"{fee_str} ({fee_pct:.2f}%)"
                else:
                    fee_display = fee_str

        # ── "To" address: first non-actor account with a net token gain ─────────
        to_addr = actor
        for idx in all_idx:
            pe = pre_tok.get(idx)
            po = post_tok.get(idx)
            owner = (po or pe or {}).get("owner")
            if not owner or owner == actor:
                continue
            pre_a  = float((pe or {}).get("uiTokenAmount", {}).get("uiAmount") or 0)
            post_a = float((po or {}).get("uiTokenAmount", {}).get("uiAmount") or 0)
            if post_a - pre_a > _MIN_CHANGE:
                to_addr = owner
                break

        # ── Value string: "X SYM_A → Y SYM_B" ────────────────────────────────
        sent_part: Optional[str] = None
        recv_part: Optional[str] = None
        if sent_items:
            it = sent_items[0]
            sent_part = f"{_fmt_amount(it['amount'])} {it['symbol']}"
        elif sol_sent > _MIN_CHANGE:
            sent_part = f"{_fmt_amount(sol_sent)} SOL"
        if received_items:
            it = received_items[0]
            recv_part = f"{_fmt_amount(it['amount'])} {it['symbol']}"
        elif sol_received > _MIN_CHANGE:
            recv_part = f"{_fmt_amount(sol_received)} SOL"

        if sent_part and recv_part:
            value_str: Optional[str] = f"{sent_part} → {recv_part}"
        elif sent_part:
            value_str = sent_part
        elif recv_part:
            value_str = recv_part
        else:
            value_str = None

        return {
            # ── Universal fields ──────────────────────────────────────────────
            "chain":           "Solana",
            "status":          "failed" if meta.get("err") else "success",
            "block_time":      tx.get("blockTime"),
            "from_addr":       actor,
            "from_addr_short": _shorten(actor),
            "to_addr":         to_addr,
            "to_addr_short":   _shorten(to_addr),
            "value":           value_str,
            "fee_sol":         f"{_fmt_amount(fee)} SOL",
            # ── Solana extras ─────────────────────────────────────────────────
            "payer":           payer,
            "payer_short":     _shorten(payer),
            "router":          router,
            "fee_display":     fee_display,
        }

    except (KeyError, IndexError, TypeError):
        return None


# ── Public API ────────────────────────────────────────────────────────────────

async def fetch_tx_summary(signature: str) -> Optional[dict]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                _RPC,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getTransaction",
                    "params": [signature, {
                        "encoding": "jsonParsed",
                        "maxSupportedTransactionVersion": 0,
                    }],
                },
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                data = await resp.json(content_type=None)

        result = data.get("result")
        if result is None:
            return None
        return _parse_summary(result)

    except aiohttp.ClientError as exc:
        logger.warning("Solana RPC request failed for %s: %s", signature, exc)
        return None
    except (KeyError, ValueError, TypeError) as exc:
        logger.warning("Failed to parse Solana transaction %s: %s", signature, exc)
        return None
