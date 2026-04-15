import logging
import asyncio
import math
from typing import Optional, Tuple, Dict, Any
from config import Config
from client.binance_ws import BinanceWSClient
from engine.execution import ExecutionEngine

logger = logging.getLogger(__name__)

class RepriceEngine:
    def __init__(self, binance_client: BinanceWSClient, execution: ExecutionEngine, threshold_price: float, up_outcome_id: str, down_outcome_id: str):
        self.binance = binance_client
        self.execution = execution
        self.threshold_price = threshold_price
        self.up_outcome_id = up_outcome_id
        self.down_outcome_id = down_outcome_id
        
        self.current_up_price = Config.UP_ASK_PRICE * 100
        self.current_down_price = Config.DOWN_ASK_PRICE * 100

    def calculate_asks(self, elapsed_seconds: int, window_duration_seconds: int = 900) -> Optional[Tuple[float, float]]:
        if self.binance.is_stale:
            logger.warning("Binance price feed is stale. Skipping reprice cycle.")
            return None
            
        btc_price = self.binance.latest_price
        if btc_price <= 0:
            return None
            
        dist_pct = abs((btc_price - self.threshold_price) / self.threshold_price)
        time_frac = min(elapsed_seconds / window_duration_seconds, 1.0)
        confidence = dist_pct * 800 * (0.5 + time_frac)
        
        fair_prob_up = 0.50 + 0.47 * math.tanh(confidence)
        if btc_price < self.threshold_price:
            fair_prob_up = 1.0 - fair_prob_up
            
        up_ask = min(round(fair_prob_up * 100) + 5, 95)
        down_ask = max(round((1 - fair_prob_up) * 100) - 5, 5)
        
        if up_ask + down_ask < 104:
            return None 
            
        return up_ask, down_ask

    async def run_cycle(self, active_order_ids: list[str], inventory_size: int, elapsed_seconds: int) -> list[str]:
        """Runs one reprice cycle and returns the new active order IDs."""
        if inventory_size <= 0:
            return active_order_ids
            
        new_prices = self.calculate_asks(elapsed_seconds)
        if not new_prices:
            return active_order_ids
            
        new_up, new_down = new_prices
        
        if abs(self.current_up_price - new_up) < 2 and abs(self.current_down_price - new_down) < 2:
            return active_order_ids
            
        logger.info(f"Repricing triggered: UP to ₦{new_up}, DOWN to ₦{new_down}")
        
        # 1. Cancel Old Orders
        await self.execution.cancel_orders(active_order_ids)
        
        # 2. Place New Orders using the actual remaining inventory_size dynamically passed
        # Multiply size by 100 to get notional amount in NGN
        amount_ngn = inventory_size * 100
        orders = [
            {"side": "SELL", "outcomeId": self.up_outcome_id, "amount": amount_ngn, "type": "LIMIT", "currency": "NGN", "price": new_up / 100.0, "timeInForce": "GTC", "postOnly": True},
            {"side": "SELL", "outcomeId": self.down_outcome_id, "amount": amount_ngn, "type": "LIMIT", "currency": "NGN", "price": new_down / 100.0, "timeInForce": "GTC", "postOnly": True}
        ]
        
        results = await self.execution.place_orders(orders)
        
        new_ids = []
        for r in results:
            if r and "id" in r:
                new_ids.append(r["id"])
                
        self.current_up_price = new_up
        self.current_down_price = new_down
        
        return new_ids
