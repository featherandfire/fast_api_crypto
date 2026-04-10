from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr, field_validator
from app.models import TransactionType


# ── Auth ──────────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class UserOut(BaseModel):
    id: int
    username: str
    email: str
    created_at: datetime
    is_verified: bool = False

    model_config = {"from_attributes": True}


class VerifyRequest(BaseModel):
    email: str
    code: str


class ResendRequest(BaseModel):
    email: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginForm(BaseModel):
    username: str
    password: str


# ── Coin ─────────────────────────────────────────────────────────────────────

class CoinOut(BaseModel):
    id: int
    coingecko_id: str
    symbol: str
    name: str
    current_price_usd: Optional[float]
    price_change_24h: Optional[float]
    market_cap: Optional[float]
    image_url: Optional[str]
    last_updated: Optional[datetime]

    model_config = {"from_attributes": True}


# ── Portfolio ─────────────────────────────────────────────────────────────────

class PortfolioCreate(BaseModel):
    name: str


class PortfolioOut(BaseModel):
    id: int
    name: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Holding ──────────────────────────────────────────────────────────────────

class HoldingCreate(BaseModel):
    coingecko_id: str
    amount: float
    avg_buy_price: Optional[float] = None


class HoldingUpdate(BaseModel):
    amount: Optional[float] = None
    avg_buy_price: Optional[float] = None


class HoldingOut(BaseModel):
    id: int
    amount: float
    avg_buy_price: Optional[float]
    created_at: datetime
    updated_at: datetime
    coin: CoinOut

    model_config = {"from_attributes": True}


class HoldingWithValue(HoldingOut):
    current_value_usd: Optional[float]
    pnl_usd: Optional[float]
    pnl_pct: Optional[float]


# ── Portfolio detail ──────────────────────────────────────────────────────────

class PortfolioDetail(PortfolioOut):
    holdings: List[HoldingWithValue]
    total_value_usd: float
    total_cost_usd: float
    total_pnl_usd: float
    total_pnl_pct: Optional[float]


# ── Transaction ───────────────────────────────────────────────────────────────

class TransactionCreate(BaseModel):
    type: TransactionType
    amount: float
    price_usd: float
    note: Optional[str] = None


class TransactionOut(BaseModel):
    id: int
    type: TransactionType
    amount: float
    price_usd: float
    timestamp: datetime
    note: Optional[str]

    model_config = {"from_attributes": True}


# ── Price history (from CoinGecko) ────────────────────────────────────────────

class PricePoint(BaseModel):
    timestamp: int  # Unix ms
    price: float


class PriceHistory(BaseModel):
    coingecko_id: str
    prices: List[PricePoint]
