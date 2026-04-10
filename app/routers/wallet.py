"""Wallet import router — fetches live ETH + ERC-20 balances from Etherscan."""
import re
import asyncio
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import etherscan, coingecko
from app.auth import get_current_user
from app.models import User

router = APIRouter(prefix="/api/wallet", tags=["wallet"])

_ETH_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_ETH_SENTINEL = "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"


class WalletToken(BaseModel):
    coingecko_id: Optional[str] = None
    contract_address: str
    name: str
    symbol: str
    amount: float
    current_price_usd: Optional[float] = None
    image_url: Optional[str] = None
    matched: bool


@router.get("/eth/{address}", response_model=List[WalletToken])
async def import_eth_wallet(
    address: str,
    _: User = Depends(get_current_user),
):
    if not _ETH_ADDRESS_RE.match(address):
        raise HTTPException(status_code=422, detail="Invalid Ethereum address format")

    try:
        balances = await etherscan.fetch_wallet_balances(address)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Etherscan error: {exc}")

    if not balances:
        return []

    # Separate ETH from ERC-20s
    eth_entry = next((b for b in balances if b["contract_address"] == _ETH_SENTINEL), None)
    erc20_entries = [b for b in balances if b["contract_address"] != _ETH_SENTINEL]

    # Fetch ETH price and contract matches concurrently
    eth_price_task = coingecko.fetch_prices(["ethereum"]) if eth_entry else asyncio.sleep(0, result={})
    contract_match_task = coingecko.match_tokens_by_contract(
        [e["contract_address"] for e in erc20_entries]
    )
    eth_prices, contract_map = await asyncio.gather(eth_price_task, contract_match_task)

    tokens: List[WalletToken] = []

    # ETH itself
    if eth_entry:
        eth_data = eth_prices.get("ethereum", {})
        tokens.append(WalletToken(
            coingecko_id="ethereum",
            contract_address=_ETH_SENTINEL,
            name="Ethereum",
            symbol="ETH",
            amount=eth_entry["balance"],
            current_price_usd=eth_data.get("current_price_usd"),
            image_url=eth_data.get("image_url"),
            matched=True,
        ))

    # ERC-20 tokens — matched first, then unmatched
    matched, unmatched = [], []
    for entry in erc20_entries:
        info = contract_map.get(entry["contract_address"])
        token = WalletToken(
            coingecko_id=info["coingecko_id"] if info else None,
            contract_address=entry["contract_address"],
            name=info["name"] if info else entry["name"],
            symbol=info["symbol"] if info else entry["symbol"],
            amount=entry["balance"],
            current_price_usd=info["current_price_usd"] if info else None,
            image_url=info["image_url"] if info else None,
            matched=bool(info),
        )
        (matched if info else unmatched).append(token)

    return tokens + matched + unmatched
