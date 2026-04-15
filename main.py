import asyncio
import logging
import sys
import argparse
from datetime import datetime, timezone
from typing import Dict, Any, Coroutine

import logger as setup_logger
from config import Config
from client.rest import BayseRestClient
from client.binance_ws import BinanceWSClient
from engine.risk import RiskEngine
from engine.state_machine import MarketStateMachine
from database import DatabaseManager

logger = logging.getLogger("BayseMain")

class MainOrchestrator:
    def __init__(self, windows_limit: int = 0):
        self.active_markets: Dict[str, asyncio.Task] = {}
        self.rest_client = BayseRestClient()
        self.db = DatabaseManager()
        self.binance_ws = BinanceWSClient()
        self.windows_processed = 0
        self.windows_limit = windows_limit if windows_limit > 0 else Config.WINDOWS_PER_DAY
        self.is_paused = False
        self._running = True

    async def spawn_market_task(self, market_data: Dict[str, Any]):
        if self.windows_processed >= self.windows_limit:
             return
             
        market_id = market_data["id"]
        event_id = market_data["eventId"]
        
        threshold = float(market_data.get("eventThreshold", 83000))
        up_outcome_id = market_data.get("outcome1Id", "")
        down_outcome_id = market_data.get("outcome2Id", "")
        
        closing_date_str = market_data.get("closingDate")
        if not closing_date_str:
            return
            
        import datetime as dt
        closing_date = datetime.fromisoformat(closing_date_str.replace('Z', '+00:00'))
        start_time = closing_date - dt.timedelta(minutes=15)
        
        if (datetime.now(timezone.utc) - start_time).total_seconds() > 15 * 60:
            return

        risk = RiskEngine()
        
        sm = MarketStateMachine(
             market_id=market_id,
             event_id=event_id,
             start_time=start_time,
             threshold=threshold,
             rest=self.rest_client,
             risk=risk,
             db=self.db,
             binance=self.binance_ws,
             up_outcome_id=up_outcome_id,
             down_outcome_id=down_outcome_id
        )
        
        logger.info(f"Spawning task for market {market_id}")
        self.windows_processed += 1
        task = asyncio.create_task(sm.run())
        self.active_markets[market_id] = task
        
        task.add_done_callback(lambda t: self.active_markets.pop(market_id, None))

    async def poll_markets(self):
        import os
        logger.info("Starting market poller...")
        while self._running:
            try:
                if os.path.exists("api_command.txt"):
                    with open("api_command.txt", "r") as f:
                        cmd = f.read().strip()
                    if cmd == "pause":
                        self.is_paused = True
                    elif cmd == "resume":
                        self.is_paused = False
                    elif cmd in ["stop", "emergency_stop"]:
                        self._running = False
                        if cmd == "emergency_stop":
                            for t in self.active_markets.values():
                                t.cancel()
                    os.remove("api_command.txt")
                    
                if self.is_paused:
                    await asyncio.sleep(10)
                    continue
                    
                # Phase 01 Spec: Daily Stop Loss Verification
                daily_pnl = self.db.get_daily_pnl()
                if daily_pnl < -Config.DAILY_STOP_LOSS:
                    logger.critical(f"DAILY STOP LOSS EXCEEDED! (₦{daily_pnl} < -₦{Config.DAILY_STOP_LOSS})")
                    print("\n[!] Daily stop reached. Type 'resume' to continue or 'stop' to halt.")
                    self.is_paused = True
                    await asyncio.sleep(10)
                    continue
                
                path = "/v1/pm/events/series/crypto-btc-15m/lean-events"
                response = await self.rest_client.request("GET", path)
                events = response.get("events", []) if isinstance(response, dict) else []
                
                open_event = next((e for e in events if e.get("status") == "open"), None)
                
                if open_event:
                    event_id = open_event["id"]
                    markets = open_event.get("markets", [])
                    if markets:
                        market = markets[0]
                        market_id = market["id"]
                        if market_id not in self.active_markets:
                            market["eventId"] = event_id
                            market["eventThreshold"] = open_event.get("eventThreshold", 83000)
                            market["closingDate"] = open_event.get("closingDate")
                            await self.spawn_market_task(market)
                            
            except Exception as e:
                logger.error(f"Error polling markets: {e}")
                
            await asyncio.sleep(10)

    async def interactive_cli(self):
        loop = asyncio.get_event_loop()
        while self._running:
             line = await loop.run_in_executor(None, input)
             line = line.strip().lower()
             if not line:
                 continue
                 
             if line == "status":
                 print(f"--- STATUS ---")
                 print(f"Windows processed: {self.windows_processed}/{self.windows_limit}")
                 print(f"Active markets: {len(self.active_markets)}")
                 print(f"Binance Price: ${self.binance_ws.latest_price}")
                 print(f"Today's P&L: ₦{self.db.get_daily_pnl()}")
             elif line == "stop":
                 print("Stopping gracefully after current windows...")
                 self._running = False
             elif line == "stop --now":
                 print("Emergency Stop triggered!")
                 self._running = False
                 for t in self.active_markets.values():
                      t.cancel()
             elif line == "pause":
                 self.is_paused = True
                 print("Bot Paused")
             elif line == "resume":
                 self.is_paused = False
                 print("Bot Resumed")
             elif line.startswith("dry-run"):
                 if "off" in line:
                     Config.DRY_RUN = False
                     print("DRY RUN DISABLED! Trading is live.")
                 elif "on" in line:
                     Config.DRY_RUN = True
                     print("DRY RUN ENABLED! Trading simulated.")
             else:
                 print(f"Unknown command: {line}")

    async def run(self):
        async with self.rest_client:
            binance_task = asyncio.create_task(self.binance_ws.connect())
            poller_task = asyncio.create_task(self.poll_markets())
            cli_task = asyncio.create_task(self.interactive_cli())
            await asyncio.gather(binance_task, poller_task, cli_task)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bayse AMM Bot v1.0")
    parser.add_argument("command", choices=["start", "status", "report", "orders"], help="Action to perform")
    parser.add_argument("--dry-run", action="store_true", default=False, help="Enable dry-run mode override")
    parser.add_argument("--windows", type=int, default=0, help="Max windows to trade")
    args = parser.parse_args()

    if args.dry_run:
         Config.DRY_RUN = True

    if args.command == "start":
        logger.info(f"STARTING BOT - DRY RUN: {Config.DRY_RUN}")
        if not Config.DRY_RUN:
             confirm = input("Confirm live trading? (yes/no): ")
             if confirm.lower() != "yes":
                  print("Live trading aborted.")
                  sys.exit(0)

        orchestrator = MainOrchestrator(windows_limit=args.windows)
        try:
            asyncio.run(orchestrator.run())
        except KeyboardInterrupt:
            logger.info("Shutting down gracefully...")
    elif args.command == "report":
        db = DatabaseManager()
        db.print_daily_report()
    else:
        print("Command not fully implemented in CLI script yet.")
