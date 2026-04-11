from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Numeric, DateTime, Boolean, ForeignKey,
    Enum as SAEnum, UniqueConstraint,
)
from sqlalchemy.orm import relationship
import enum

from app.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    is_verified = Column(Boolean, default=False, nullable=False, server_default="0")
    verification_code = Column(String(6), nullable=True)
    verification_expires = Column(DateTime(timezone=True), nullable=True)

    portfolios = relationship("Portfolio", back_populates="owner", cascade="all, delete-orphan")


class Portfolio(Base):
    __tablename__ = "portfolios"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    owner = relationship("User", back_populates="portfolios")
    holdings = relationship("Holding", back_populates="portfolio", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_portfolio_user_name"),)


class Coin(Base):
    __tablename__ = "coins"

    id = Column(Integer, primary_key=True, index=True)
    coingecko_id = Column(String(100), unique=True, nullable=False, index=True)
    symbol = Column(String(20), nullable=False)
    name = Column(String(100), nullable=False)
    current_price_usd = Column(Numeric(19, 8), nullable=True)
    price_change_24h = Column(Numeric(10, 4), nullable=True)
    market_cap = Column(Numeric(30, 2), nullable=True)
    image_url = Column(String(500), nullable=True)
    last_updated = Column(DateTime(timezone=True), nullable=True)

    holdings = relationship("Holding", back_populates="coin")


class Holding(Base):
    __tablename__ = "holdings"

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False)
    coin_id = Column(Integer, ForeignKey("coins.id", ondelete="CASCADE"), nullable=False)
    amount = Column(Numeric(28, 10), nullable=False, default=0)
    avg_buy_price = Column(Numeric(19, 8), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    portfolio = relationship("Portfolio", back_populates="holdings")
    coin = relationship("Coin", back_populates="holdings")
    transactions = relationship("Transaction", back_populates="holding", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("portfolio_id", "coin_id", name="uq_holding_portfolio_coin"),)


class TransactionType(str, enum.Enum):
    buy = "buy"
    sell = "sell"


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    holding_id = Column(Integer, ForeignKey("holdings.id", ondelete="CASCADE"), nullable=False)
    type = Column(SAEnum(TransactionType), nullable=False)
    amount = Column(Numeric(28, 10), nullable=False)
    price_usd = Column(Numeric(19, 8), nullable=False)
    timestamp = Column(DateTime(timezone=True), default=utcnow)
    note = Column(String(500), nullable=True)

    holding = relationship("Holding", back_populates="transactions")
