# Crypto Portfolio Tracker

JWT-authenticated portfolio manager with live CoinGecko prices, Alpine.js frontend, and Chart.js visualizations.

## Stack

| Layer | Technology |
|---|---|
| API | FastAPI + async SQLAlchemy |
| Auth | JWT (python-jose) + bcrypt (passlib) |
| DB | SQLite via aiosqlite (swap for PostgreSQL in prod) |
| Prices | CoinGecko REST — concurrent aiohttp fetches |
| Frontend | Alpine.js 3 + Chart.js 4 |
| Reverse proxy | Caddy (auto-TLS) |
| Process manager | systemd |

## Local dev

```bash
cp .env.example .env
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
# Open http://localhost:8000
```

## Deploy to VPS

```bash
bash deploy.sh yourdomain.com
```

## API reference

Interactive docs at `/docs` (Swagger UI) and `/redoc`.

### Auth
| Method | Path | Description |
|---|---|---|
| POST | `/api/auth/register` | Create account |
| POST | `/api/auth/token` | Login → JWT |
| GET  | `/api/auth/me` | Current user |

### Portfolios
| Method | Path | Description |
|---|---|---|
| GET    | `/api/portfolios` | List portfolios |
| POST   | `/api/portfolios` | Create portfolio |
| GET    | `/api/portfolios/{id}` | Portfolio detail + live prices |
| DELETE | `/api/portfolios/{id}` | Delete portfolio |

### Holdings
| Method | Path | Description |
|---|---|---|
| POST   | `/api/portfolios/{id}/holdings` | Add holding |
| PATCH  | `/api/portfolios/{id}/holdings/{hid}` | Update amount/avg price |
| DELETE | `/api/portfolios/{id}/holdings/{hid}` | Remove holding |

### Transactions
| Method | Path | Description |
|---|---|---|
| POST | `/api/portfolios/{id}/holdings/{hid}/transactions` | Log buy/sell |
| GET  | `/api/portfolios/{id}/holdings/{hid}/transactions` | List transactions |

### Coins
| Method | Path | Description |
|---|---|---|
| GET | `/api/coins/top?limit=50` | Top coins by market cap |
| GET | `/api/coins/search?q=...` | Search CoinGecko |
| GET | `/api/coins/{id}/history?days=30` | Price history |
