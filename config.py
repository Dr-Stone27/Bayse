import os
from dotenv import load_dotenv

load_dotenv()

def _require(key: str) -> str:
    val = os.getenv(key, "")
    if not val:
        raise ValueError(f"Required environment variable '{key}' is not set in .env")
    return val

class Config:
    # Authentication (write endpoints need both; read endpoints only need public key)
    PUBLIC_KEY: str = os.getenv("BAYSE_PUBLIC_KEY", "")
    SECRET_KEY: str = os.getenv("BAYSE_SECRET_KEY", "")

    # Connections
    REST_URL: str = "https://relay.bayse.markets"
    BAYSE_WS_URL: str = "wss://socket.bayse.markets/ws/v1/markets"
    BINANCE_WS_URL: str = "wss://stream.binance.com:9443/ws/btcusdt@aggTrade"

    # Strategy: Capital
    BTC_MINT_AMOUNT: int   = int(os.getenv("BTC_MINT_AMOUNT", "500"))
    ETH_MINT_AMOUNT: int   = int(os.getenv("ETH_MINT_AMOUNT", "500"))

    # Strategy: Pricing
    UP_ASK_PRICE: float    = float(os.getenv("UP_ASK_PRICE", "0.52"))
    DOWN_ASK_PRICE: float  = float(os.getenv("DOWN_ASK_PRICE", "0.54"))

    # Strategy: Timing
    WINDOWS_PER_DAY: int   = int(os.getenv("WINDOWS_PER_DAY", "6"))
    BURN_AT_MINUTE: int    = int(os.getenv("BURN_AT_MINUTE", "13"))
    REPRICE_INTERVAL_SEC: int = int(os.getenv("REPRICE_INTERVAL_SEC", "30"))

    # Risk Controls
    KILL_SWITCH_RATIO: float       = float(os.getenv("KILL_SWITCH_RATIO", "0.90"))
    DAILY_STOP_LOSS: int           = int(os.getenv("DAILY_STOP_LOSS", "2000"))
    MAX_SINGLE_WINDOW_LOSS: int    = int(os.getenv("MAX_SINGLE_WINDOW_LOSS", "500"))
    BURN_RETRY_INTERVAL_MS: int    = int(os.getenv("BURN_RETRY_INTERVAL_MS", "200"))

    # Operations
    DRY_RUN: bool          = os.getenv("DRY_RUN", "true").lower() == "true"
    LOG_LEVEL: str         = os.getenv("LOG_LEVEL", "info").upper()
    DB_PATH: str           = os.getenv("DB_PATH", "./bayse_market_making.db")

    # Binance feed health threshold
    BINANCE_STALE_THRESHOLD_SEC: int = 5
