import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from client.rest import BayseRestClient
from config import Config

logger = logging.getLogger(__name__)

class ExecutionEngine:
    def __init__(self, rest_client: BayseRestClient, market_id: str, event_id: str):
        self.rest_client = rest_client
        self.market_id = market_id
        self.event_id = event_id

    async def mint_shares(self, amount: int) -> bool:
        try:
            logger.info(f"Minting ₦{amount} shares for market {self.market_id}")
            path = f"/v1/pm/markets/{self.market_id}/mint"
            quantity = amount // 100
            payload = {"quantity": quantity, "currency": "NGN"}
            await self.rest_client.request("POST", path, data=payload)
            return True
        except Exception as e:
            logger.error(f"Failed to mint shares: {e}")
            return False

    async def place_orders(self, orders: List[Dict[str, Any]]) -> List[Optional[Dict[str, Any]]]:
        async def _place_single_order(order_data: Dict[str, Any]):
            try:
                path = f"/v1/pm/events/{self.event_id}/markets/{self.market_id}/orders"
                result = await self.rest_client.request("POST", path, data=order_data)
                return result
            except Exception as e:
                logger.error(f"Failed to place order {order_data}: {e}")
                return None

        # Gather tasks concurrently
        tasks = [_place_single_order(o) for o in orders]
        return await asyncio.gather(*tasks)

    async def cancel_orders(self, order_ids: List[str]):
        async def _cancel_single_order(order_id: str):
            try:
                path = f"/v1/pm/orders/{order_id}"
                await self.rest_client.request("DELETE", path)
            except Exception as e:
                logger.error(f"Failed to cancel order {order_id}: {e}")

        tasks = [_cancel_single_order(oid) for oid in order_ids]
        await asyncio.gather(*tasks)

    async def cancel_all_and_burn(self, active_order_ids: List[str], window_start_time: float, amount_ngn: int) -> bool:
        await self.cancel_orders(active_order_ids)
        return await self.burn_shares(window_start_time, amount_ngn)

    async def burn_shares(self, window_start_time: float, amount_ngn: int) -> bool:
        """Attempt to burn shares. Strict T+14:30 hard stop logic."""
        path = f"/v1/pm/markets/{self.market_id}/burn"
        logger.info(f"Attempting to burn inventory for market {self.market_id}")
        
        while True:
            # Emergency Stop Trigger (T+14:30 = 870 seconds)
            current_time = datetime.now(timezone.utc).timestamp()
            if (current_time - window_start_time) > 870:
                logger.critical(f"BURN HARD STOP (T+14:30 exceeded). Market {self.market_id} remaining pairs are stranded.")
                return False

            try:
                payload = {"quantity": amount_ngn, "currency": "NGN"}
                await self.rest_client.request("POST", path, data=payload)
                logger.info(f"Burn successful for market {self.market_id}")
                return True
            except Exception as e:
                logger.warning(f"Burn API failed: {e}. Retrying in {Config.BURN_RETRY_INTERVAL_MS}ms...")
                await asyncio.sleep(Config.BURN_RETRY_INTERVAL_MS / 1000.0)
