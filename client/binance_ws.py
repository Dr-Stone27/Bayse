import asyncio
import websockets
import json
import logging
from datetime import datetime, timezone
from config import Config

logger = logging.getLogger(__name__)

class BinanceWSClient:
    def __init__(self):
        self._running = False
        self._latest_price = 0.0
        self._last_update_time = 0.0
        self._ws = None

    @property
    def latest_price(self) -> float:
        return self._latest_price

    @property
    def is_stale(self) -> bool:
        """Returns True if the last price update was more than STALE_THRESHOLD_SEC ago."""
        if self._last_update_time == 0.0:
            return True
        now = datetime.now(timezone.utc).timestamp()
        return (now - self._last_update_time) > Config.BINANCE_STALE_THRESHOLD_SEC

    async def connect(self):
        self._running = True
        retry_count = 0
        max_retries = 5
        base_backoff = 1

        while self._running:
            try:
                logger.info(f"Connecting to Binance WS: {Config.BINANCE_WS_URL}")
                async with websockets.connect(Config.BINANCE_WS_URL) as websocket:
                    self._ws = websocket
                    retry_count = 0  # reset on successful connection
                    logger.info("Connected to Binance target price feed")
                    
                    async for message in websocket:
                        if not self._running:
                            break
                        data = json.loads(message)
                        if "p" in data:
                            self._latest_price = float(data["p"])
                            self._last_update_time = datetime.now(timezone.utc).timestamp()
                        
            except websockets.exceptions.ConnectionClosed:
                logger.warning("Binance WS closed. Attempting reconnect...")
            except Exception as e:
                logger.error(f"Binance WS Error: {e}")
            
            if not self._running:
                break
                
            # Exponential backoff
            retry_count += 1
            if retry_count > max_retries:
                logger.critical("Binance WS disconnected for too long (max retries exceeded).")
                # Wait longer before trying again
                await asyncio.sleep(30)
                retry_count = 0
            else:
                backoff = base_backoff * (2 ** (retry_count - 1))
                await asyncio.sleep(backoff)

    async def disconnect(self):
        self._running = False
        if self._ws:
            await self._ws.close()
