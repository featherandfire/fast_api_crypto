from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import coingecko
from app.auth import get_current_user
from app.database import get_db
from app.models import Coin, Holding, Portfolio, Transaction, User
from app.schemas import (
    HoldingCreate, HoldingOut, HoldingUpdate, HoldingWithValue,
    PortfolioCreate, PortfolioDetail, PortfolioOut,
    TransactionCreate, TransactionOut,
)

router = APIRouter(prefix="/api/portfolios", tags=["portfolios"])


def _now():
    return datetime.now(timezone.utc)


def _compute_holding_value(holding: Holding) -> HoldingWithValue:
    price = holding.coin.current_price_usd
    current_value = holding.amount * price if price is not None else None
    cost = (holding.avg_buy_price or 0) * holding.amount
    pnl_usd = (current_value - cost) if current_value is not None else None
    pnl_pct = (pnl_usd / cost * 100) if (pnl_usd is not None and cost > 0) else None
    return HoldingWithValue(
        **HoldingOut.model_validate(holding).model_dump(),
        current_value_usd=current_value,
        pnl_usd=pnl_usd,
        pnl_pct=pnl_pct,
    )


async def _get_or_create_coin(db: AsyncSession, coingecko_id: str) -> Coin:
    result = await db.execute(select(Coin).where(Coin.coingecko_id == coingecko_id))
    coin = result.scalar_one_or_none()
    if coin is None:
        # Fetch basic info from CoinGecko
        data = await coingecko.fetch_prices([coingecko_id])
        if coingecko_id not in data:
            raise HTTPException(status_code=404, detail=f"Coin '{coingecko_id}' not found on CoinGecko")
        d = data[coingecko_id]
        coin = Coin(
            coingecko_id=coingecko_id,
            symbol=d["symbol"],
            name=d["name"],
            current_price_usd=d["current_price_usd"],
            price_change_24h=d["price_change_24h"],
            market_cap=d["market_cap"],
            image_url=d["image_url"],
            last_updated=_now(),
        )
        db.add(coin)
        await db.flush()
    return coin


async def _refresh_holding_prices(db: AsyncSession, holdings: list[Holding]):
    """Concurrently refresh prices for all coins in a list of holdings."""
    coin_ids = list({h.coin.coingecko_id for h in holdings})
    if not coin_ids:
        return
    prices = await coingecko.fetch_prices(coin_ids)
    for holding in holdings:
        cid = holding.coin.coingecko_id
        if cid in prices:
            holding.coin.current_price_usd = prices[cid]["current_price_usd"]
            holding.coin.price_change_24h = prices[cid]["price_change_24h"]
            holding.coin.last_updated = _now()
    await db.commit()


# ── Portfolio CRUD ────────────────────────────────────────────────────────────

@router.get("", response_model=List[PortfolioOut])
async def list_portfolios(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Portfolio).where(Portfolio.user_id == current_user.id)
    )
    return result.scalars().all()


@router.post("", response_model=PortfolioOut, status_code=status.HTTP_201_CREATED)
async def create_portfolio(
    payload: PortfolioCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    portfolio = Portfolio(user_id=current_user.id, name=payload.name)
    db.add(portfolio)
    await db.commit()
    await db.refresh(portfolio)
    return portfolio


@router.get("/{portfolio_id}", response_model=PortfolioDetail)
async def get_portfolio(
    portfolio_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Portfolio)
        .where(Portfolio.id == portfolio_id, Portfolio.user_id == current_user.id)
        .options(selectinload(Portfolio.holdings).selectinload(Holding.coin))
    )
    portfolio = result.scalar_one_or_none()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    await _refresh_holding_prices(db, portfolio.holdings)

    holdings_out = [_compute_holding_value(h) for h in portfolio.holdings]
    total_value = sum(h.current_value_usd or 0 for h in holdings_out)
    total_cost = sum((h.avg_buy_price or 0) * h.amount for h in portfolio.holdings)
    total_pnl = total_value - total_cost
    pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else None

    return PortfolioDetail(
        **PortfolioOut.model_validate(portfolio).model_dump(),
        holdings=holdings_out,
        total_value_usd=total_value,
        total_cost_usd=total_cost,
        total_pnl_usd=total_pnl,
        total_pnl_pct=pnl_pct,
    )


@router.delete("/{portfolio_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_portfolio(
    portfolio_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Portfolio).where(Portfolio.id == portfolio_id, Portfolio.user_id == current_user.id)
    )
    portfolio = result.scalar_one_or_none()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    await db.delete(portfolio)
    await db.commit()


# ── Holding CRUD ──────────────────────────────────────────────────────────────

@router.post("/{portfolio_id}/holdings", response_model=HoldingOut, status_code=status.HTTP_201_CREATED)
async def add_holding(
    portfolio_id: int,
    payload: HoldingCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Portfolio).where(Portfolio.id == portfolio_id, Portfolio.user_id == current_user.id)
    )
    portfolio = result.scalar_one_or_none()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    coin = await _get_or_create_coin(db, payload.coingecko_id)

    existing = await db.execute(
        select(Holding).where(Holding.portfolio_id == portfolio_id, Holding.coin_id == coin.id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Coin already in portfolio; use PATCH to update")

    holding = Holding(
        portfolio_id=portfolio_id,
        coin_id=coin.id,
        amount=payload.amount,
        avg_buy_price=payload.avg_buy_price,
    )
    db.add(holding)
    await db.commit()
    await db.refresh(holding)

    result2 = await db.execute(
        select(Holding).where(Holding.id == holding.id).options(selectinload(Holding.coin))
    )
    return result2.scalar_one()


@router.patch("/{portfolio_id}/holdings/{holding_id}", response_model=HoldingOut)
async def update_holding(
    portfolio_id: int,
    holding_id: int,
    payload: HoldingUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Holding)
        .join(Portfolio)
        .where(
            Holding.id == holding_id,
            Holding.portfolio_id == portfolio_id,
            Portfolio.user_id == current_user.id,
        )
        .options(selectinload(Holding.coin))
    )
    holding = result.scalar_one_or_none()
    if not holding:
        raise HTTPException(status_code=404, detail="Holding not found")

    if payload.amount is not None:
        holding.amount = payload.amount
    if payload.avg_buy_price is not None:
        holding.avg_buy_price = payload.avg_buy_price
    holding.updated_at = _now()

    await db.commit()
    await db.refresh(holding)
    return holding


@router.delete("/{portfolio_id}/holdings/{holding_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_holding(
    portfolio_id: int,
    holding_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Holding)
        .join(Portfolio)
        .where(
            Holding.id == holding_id,
            Holding.portfolio_id == portfolio_id,
            Portfolio.user_id == current_user.id,
        )
    )
    holding = result.scalar_one_or_none()
    if not holding:
        raise HTTPException(status_code=404, detail="Holding not found")
    await db.delete(holding)
    await db.commit()


# ── Transactions ──────────────────────────────────────────────────────────────

@router.post("/{portfolio_id}/holdings/{holding_id}/transactions", response_model=TransactionOut, status_code=status.HTTP_201_CREATED)
async def add_transaction(
    portfolio_id: int,
    holding_id: int,
    payload: TransactionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Holding)
        .join(Portfolio)
        .where(
            Holding.id == holding_id,
            Holding.portfolio_id == portfolio_id,
            Portfolio.user_id == current_user.id,
        )
    )
    holding = result.scalar_one_or_none()
    if not holding:
        raise HTTPException(status_code=404, detail="Holding not found")

    tx = Transaction(
        holding_id=holding_id,
        type=payload.type,
        amount=payload.amount,
        price_usd=payload.price_usd,
        note=payload.note,
    )
    db.add(tx)
    await db.commit()
    await db.refresh(tx)
    return tx


@router.get("/{portfolio_id}/holdings/{holding_id}/transactions", response_model=List[TransactionOut])
async def list_transactions(
    portfolio_id: int,
    holding_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Transaction)
        .join(Holding)
        .join(Portfolio)
        .where(
            Transaction.holding_id == holding_id,
            Holding.portfolio_id == portfolio_id,
            Portfolio.user_id == current_user.id,
        )
        .order_by(Transaction.timestamp.desc())
    )
    return result.scalars().all()
