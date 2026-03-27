from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Position:
    lat: float
    lon: float
    alt: float = 0.0
    speed: float = 0.0  # knots
    course: float = 0.0  # degrees true
    fix: bool = False
    sats: int = 0
    timestamp: datetime = field(default_factory=datetime.utcnow)
