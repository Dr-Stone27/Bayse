import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from config import Config
from client.rest import BayseRestClient
from client.ws import BayseWSClient
from client.binance_ws import BinanceWSClient
from engine.execution import ExecutionEngine
from engine.risk import RiskEngine
from engine.reprice_engine import RepriceEngine
from database import DatabaseManager

logger = logging.getLogger(__name__)

class MarketStateMachine:
    def __init__(self, market_id: str, event_id: str, start_time: datetime, threshold: float, 
                 rest: BayseRestClient, risk: RiskEngine, db: DatabaseManager, binance: BinanceWSClient,
                 up_outcome_id: str, down_outcome_id: str):
        self.market_id = market_id
        self.event_id = event_id
        self.start_time = start_time
        self.threshold = threshold
        self.up_outcome_id = up_outcome_id
        self.down_outcome_id = down_outcome_id
        
        self.rest = rest
        self.risk = risk
        self.db = db
        self.binance = binance
        
        self.execution = ExecutionEngine(self.rest, market_id, event_id)
        self.reprice = RepriceEngine(self.binance, self.execution, self.threshold, self.up_outcome_id, self.down_outcome_id)
        
        self.ws = BayseWSClient(self.event_id, self.market_id, self._on_ws_message)
        
        self.active_order_ids: List[str] = []
        self.phase = "INIT"
        self._kill_triggered = False
        self.db_window_id: Optional[int] = None
        
        self.pairs_minted = 0

    async def _on_ws_message(self, data: Dict[str, Any]):
        channel = data.get("channel")
        if channel == "activity":
            event = data.get("event", {})
            if event.get("type") == "fill":
                outcome = event.get("outcome", "")
                size = event.get("size", 0)
                price = event.get("price", 0.0)
                
                # Update DB first
                if self.db_window_id:
                    self.db.insert_fill({
                        "window_id": self.db_window_id,
                        "filled_at": datetime.utcnow().isoformat(),
                        "side": outcome,
                        "shares": size,
                        "price_ngn": price,
                        "elapsed_seconds": int(datetime.now(timezone.utc).timestamp() - self.start_time.timestamp()),
                        "order_id": event.get("orderId", "")
                    })
                # Send to risk
                self.risk.process_fill(outcome, size)

    async def run(self):
        """Run the strict T+ phase state machine."""
        if Config.DRY_RUN:
            logger.info(f"DRY RUN: Starting state machine for market {self.market_id}")
            
        try:
            ws_task = asyncio.create_task(self.ws.connect())
            
            # Phase 01: Pre-window Setup (T-30s)
            logger.info(f"Phase 1: Pre-window checks for {self.market_id}")
            res = await self.rest.request("GET", "/v1/pm/orders?status=open")
            open_orders = res if isinstance(res, list) else res.get("data", [])
            if open_orders and not Config.DRY_RUN:
                logger.warning(f"Found {len(open_orders)} open orders from previous run. Canceling.")
                await self.execution.cancel_orders([o["id"] for o in open_orders])

            await self._wait_until_offset(0)
            
            # Phase 02: Mint pairs (T+0:00)
            self.phase = "MINT"
            logger.info(f"MINTED - {self.market_id}. Capital: ₦{Config.BTC_MINT_AMOUNT}")
            
            self.pairs_minted = Config.BTC_MINT_AMOUNT // 100
            self.db_window_id = self.db.insert_window({
                "market": "BTC",
                "opened_at": datetime.utcnow().isoformat(),
                "threshold_price": self.threshold,
                "binance_open_price": self.binance.latest_price if self.binance else 0,
                "mint_amount_ngn": Config.BTC_MINT_AMOUNT,
                "pairs_minted": self.pairs_minted
            })
            
            if not Config.DRY_RUN:
                success = await self.execution.mint_shares(Config.BTC_MINT_AMOUNT)
                if not success:
                    logger.error("Mint failed. Aborting.")
                    return

            # Phase 03: Post orders (T+0:15)
            await self._wait_until_offset(15)
            self.phase = "QUOTE"
            logger.info("ORDERS POST - Initializing dynamically")
            
            amount_ngn = self.pairs_minted * 100
            elapsed_seconds = int(datetime.now(timezone.utc).timestamp() - self.start_time.timestamp())
            initial_asks = self.reprice.calculate_asks(max(elapsed_seconds, 0))
            if initial_asks:
                up_ask = initial_asks[0] / 100.0
                down_ask = initial_asks[1] / 100.0
            else:
                up_ask = Config.UP_ASK_PRICE
                down_ask = Config.DOWN_ASK_PRICE
            
            orders = [
                {"side": "SELL", "outcomeId": self.up_outcome_id, "amount": amount_ngn, "type": "LIMIT", "currency": "NGN", "price": up_ask, "timeInForce": "GTC", "postOnly": True},
                {"side": "SELL", "outcomeId": self.down_outcome_id, "amount": amount_ngn, "type": "LIMIT", "currency": "NGN", "price": down_ask, "timeInForce": "GTC", "postOnly": True}
            ]
            if not Config.DRY_RUN:
                results = await self.execution.place_orders(orders)
                for r in results:
                    if r and "id" in r:
                        self.active_order_ids.append(r["id"])

            # Phase 04: Active Monitoring + Reprice (T+1:00 -> T+12:59)
            await self._wait_until_offset(60)
            self.phase = "MONITOR"
            monitor_task = asyncio.create_task(self._monitor_and_reprice_loop())
            
            wait_for_burn = asyncio.create_task(self._wait_until_offset(Config.BURN_AT_MINUTE * 60))
            
            done, pending = await asyncio.wait(
                [monitor_task, wait_for_burn],
                return_when=asyncio.FIRST_COMPLETED
            )
            for t in pending:
                t.cancel()

            # Phase 05: Burn sequence (T+13:00)
            self.phase = "BURN"
            logger.info("BURN START - Canceling open orders and burning")
            if not Config.DRY_RUN:
                # Execution engine handles T+14:30 hard stop tracking internally now
                remaining_shares = max(0, self.pairs_minted - max(self.risk.position.up_filled, self.risk.position.down_filled))
                await self.execution.cancel_all_and_burn(self.active_order_ids, self.start_time.timestamp(), remaining_shares * 100)
                
            # Phase 07: Resolve (T+15:00)
            await self._wait_until_offset(15 * 60)
            self.phase = "RESOLVE"
            logger.info("RESOLVED - Fetching state & logging P&L.")
            
            if not Config.DRY_RUN and self.db_window_id:
                 # Real P&L calculation would hit portfolio API to derive burn_recovered and singles payouts
                 # Example derivation of basic flow:
                 # portfolio = await self.rest.request("GET", "/v1/pm/portfolio")
                 
                 # Placeholder calc for spec compliance DB insert wrapper
                 net_pnl = 0  # To be calculated accurately based on fill prices + resolutions - mint
                 self.db.update_window(self.db_window_id, {
                     "resolution": "RESOLVED",
                     "net_pnl_ngn": net_pnl,
                 })

        except Exception as e:
            logger.error(f"State Machine exception: {e}")
        finally:
            await self.ws.disconnect()

    async def _monitor_and_reprice_loop(self):
        try:
            while True:
                # 1. Kill-Switch
                if self.risk.check_toxicity() and not self._kill_triggered:
                    logger.critical(f"KILL SWITCH TRIGGERED for {self.market_id}!")
                    self._kill_triggered = True
                    if self.db_window_id:
                        self.db.update_window(self.db_window_id, {"kill_switch_fired": 1, "kill_switch_reason": "Toxicity fill ratio threshold"})
                    if not Config.DRY_RUN:
                        remaining_shares = max(0, self.pairs_minted - max(self.risk.position.up_filled, self.risk.position.down_filled))
                        await self.execution.cancel_all_and_burn(self.active_order_ids, self.start_time.timestamp(), remaining_shares * 100)
                    return 
                
                # 2. Reprice
                if not Config.DRY_RUN and not self._kill_triggered:
                    # Calculates remaining inventory to avoid placing 50 size asks when we only have 2 left
                    remaining_inventory = max(0, self.pairs_minted - max(self.risk.position.up_filled, self.risk.position.down_filled))
                    elapsed_seconds = int(datetime.now(timezone.utc).timestamp() - self.start_time.timestamp())
                    if remaining_inventory > 0:
                         self.active_order_ids = await self.reprice.run_cycle(self.active_order_ids, remaining_inventory, max(elapsed_seconds, 0))
                    if self.db_window_id:
                         # we could log increment reprice count here
                         pass
                
                await asyncio.sleep(Config.REPRICE_INTERVAL_SEC)
        except asyncio.CancelledError:
            pass

    async def _wait_until_offset(self, seconds_offset: int):
        target = self.start_time.timestamp() + seconds_offset
        wait_time = target - datetime.now(timezone.utc).timestamp()
        if wait_time > 0:
            await asyncio.sleep(wait_time)
