import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from fastapi.responses import HTMLResponse

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from app.database import init_db, engine
from app.routers import auth, portfolio, coins, wallet, lookup

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # Add verification columns to existing DBs (safe no-op if already present)
    async with engine.begin() as conn:
        for stmt in [
            "ALTER TABLE users ADD COLUMN is_verified INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE users ADD COLUMN verification_code VARCHAR(6)",
            "ALTER TABLE users ADD COLUMN verification_expires DATETIME",
        ]:
            try:
                await conn.execute(text(stmt))
            except OperationalError:
                pass  # column already exists — safe to skip
    yield


app = FastAPI(
    title="Crypto Portfolio Tracker",
    description="JWT-authenticated portfolio manager with live CoinGecko prices",
    version="1.0.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Routers
app.include_router(auth.router)
app.include_router(portfolio.router)
app.include_router(coins.router)
app.include_router(wallet.router)
app.include_router(lookup.router)


# ── SPA catch-all ─────────────────────────────────────────────────────────────

@app.get("/{full_path:path}", response_class=HTMLResponse, include_in_schema=False)
async def spa(request: Request, full_path: str):
    return templates.TemplateResponse("index.html", {"request": request})
