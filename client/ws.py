import asyncio
import websockets
import json
import logging
from typing import Callable, Coroutine, Dict, Any
from config import Config

logger = logging.getLogger(__name__)

class BayseWSClient:
    def __init__(self, event_id: str, market_id: str, on_message_callback: Callable[[Dict[str, Any]], Coroutine]):
        self.event_id = event_id
        self.market_id = market_id
        self.on_message_callback = on_message_callback
        self.ws = None
        self._running = False
        
    async def connect(self):
        self._running = True
        while self._running:
            try:
                async with websockets.connect(Config.BAYSE_WS_URL) as websocket:
                    self.ws = websocket
                    
                    # 1. Subscribe to orderbook
                    ob_msg = {
                        "type": "subscribe",
                        "channel": "orderbook",
                        "marketIds": [self.market_id],
                        "currency": "NGN"
                    }
                    await self.ws.send(json.dumps(ob_msg))

                    # 2. Subscribe to activity
                    act_msg = {
                        "type": "subscribe",
                        "channel": "activity",
                        "eventId": self.event_id
                    }
                    await self.ws.send(json.dumps(act_msg))

                    # 3. Subscribe to prices
                    price_msg = {
                        "type": "subscribe",
                        "channel": "prices",
                        "eventId": self.event_id
                    }
                    await self.ws.send(json.dumps(price_msg))
                    
                    logger.info(f"Connected to Bayse WS for market {self.market_id}")
                    
                    async for message in self.ws:
                        if not self._running:
                            break
                        data = json.loads(message)
                        asyncio.create_task(self.on_message_callback(data))
                        
            except websockets.exceptions.ConnectionClosed:
                logger.warning(f"WS Connection closed for {self.market_id}. Reconnecting in 1s...")
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"WS Error for {self.market_id}: {e}")
                await asyncio.sleep(1)

    async def disconnect(self):
        self._running = False
        if self.ws:
            await self.ws.close()
