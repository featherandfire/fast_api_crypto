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
