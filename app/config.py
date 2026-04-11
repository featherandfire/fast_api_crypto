from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    secret_key: str  # required — no default; set SECRET_KEY in .env
    database_url: str = "sqlite+aiosqlite:///./crypto_portfolio.db"
    access_token_expire_minutes: int = 60
    coingecko_base_url: str = "https://api.coingecko.com/api/v3"
    etherscan_api_key: str = ""
    etherscan_base_url: str = "https://api.etherscan.io/v2/api"
    algorithm: str = "HS256"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
