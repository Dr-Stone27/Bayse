from dataclasses import dataclass, field
from typing import Optional, Dict

@dataclass
class Market:
    id: str
    event_id: str
    start_time: str
    end_time: str
    status: str
    currency: str

@dataclass
class Order:
    id: str
    market_id: str
    side: str  # 'buy' or 'sell'
    outcome: str # 'Up' or 'Down'
    price: float
    size: int
    status: str

@dataclass
class PositionTracking:
    up_filled: int = 0
    down_filled: int = 0
    total_filled: int = 0
    
    @property
    def toxicity_ratio(self) -> float:
        if self.total_filled == 0:
            return 0.0
        return max(self.up_filled, self.down_filled) / self.total_filled
