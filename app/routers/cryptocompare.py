from fastapi import APIRouter, Depends, Query
from app import cryptocompare
from app.auth import get_current_user
from app.models import User

router = APIRouter(prefix="/api/cryptocompare", tags=["cryptocompare"])


@router.get("/changes")
async def get_pct_changes(
    symbols: str = Query(..., description="Comma-separated uppercase symbols"),
    days: str = Query("548", description="Comma-separated day counts"),
    _: User = Depends(get_current_user),
):
    """Return {SYMBOL: {days: pct_change}} for requested symbols and day ranges."""
    sym_list = [s.strip() for s in symbols.split(",") if s.strip()][:50]
    day_list = [int(d.strip()) for d in days.split(",") if d.strip().isdigit()][:5]
    return await cryptocompare.fetch_pct_changes(sym_list, day_list)


@router.get("/volatility")
async def get_volatility(
    symbols: str = Query(..., description="Comma-separated uppercase symbols"),
    days: str = Query("90,180", description="Comma-separated day periods"),
    _: User = Depends(get_current_user),
):
    """Return {SYMBOL: {days: annualized_volatility}} for requested symbols."""
    sym_list = [s.strip() for s in symbols.split(",") if s.strip()][:200]
    day_list = [int(d.strip()) for d in days.split(",") if d.strip().isdigit()][:5]
    return await cryptocompare.fetch_volatilities(sym_list, day_list)
