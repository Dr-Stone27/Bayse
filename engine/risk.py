import collections
import statistics
import logging
from typing import Deque
from config import Config
from models import PositionTracking

logger = logging.getLogger(__name__)

class RiskEngine:
    def __init__(self):
        self.rtt_history: Deque[float] = collections.deque(maxlen=10)
        self.position = PositionTracking()
        self.midpoint: float = 0.5 # Default starting point
        self.is_multi_layer_enabled: bool = True
        
    def add_latency_ping(self, rtt_ms: float):
        self.rtt_history.append(rtt_ms)
        rolling_avg = statistics.mean(self.rtt_history)
        
        if rolling_avg > Config.MINIMUM_LATENCY_MS:
            if self.is_multi_layer_enabled:
                logger.warning(f"High latency detected ({rolling_avg:.2f}ms). Disabling multi-layer quoting.")
                self.is_multi_layer_enabled = False
        else:
            if not self.is_multi_layer_enabled:
                logger.info(f"Latency recovered ({rolling_avg:.2f}ms). Re-enabling multi-layer quoting.")
                self.is_multi_layer_enabled = True

    def calculate_midpoint(self, best_bid: float, best_ask: float):
        if best_bid > 0 and best_ask > 0:
            self.midpoint = (best_bid + best_ask) / 2.0
            
    def process_fill(self, outcome: str, size: int):
        if outcome.lower() == "up":
            self.position.up_filled += size
        elif outcome.lower() == "down":
            self.position.down_filled += size
            
        self.position.total_filled += size

    def check_toxicity(self) -> bool:
        """
        Evaluate Toxicity Kill-Switch.
        If Fill Ratio >= KILL_SWITCH_FILL_RATIO, returns True (Toxic, need to kill)
        """
        if self.position.total_filled == 0:
            return False
            
        ratio = self.position.toxicity_ratio
        is_toxic = ratio >= Config.KILL_SWITCH_FILL_RATIO
        if is_toxic:
            logger.critical(f"Toxicity limit reached! Ratio: {ratio:.2f}. Triggering Kill-Switch.")
        return is_toxic
