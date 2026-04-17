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
    paxos_client_id: str = ""
    paxos_client_secret: str = ""
    paxos_profile_id: str = ""
    paxos_base_url: str = "https://api.sandbox.paxos.com/v2"
    paxos_oauth_url: str = "https://oauth.sandbox.paxos.com/oauth2/token"
    cryptocompare_api_key: str = ""
    cryptocompare_base_url: str = "https://min-api.cryptocompare.com"

    class Config:
        env_file = ".env"


settings = Settings()
