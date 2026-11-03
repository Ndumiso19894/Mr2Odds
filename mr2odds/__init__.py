"""Mr2Odds goal scanner."""

from .models import Match, Market, Opportunity
from .scanner import GoalScanner, ScanResult

__all__ = ["Match", "Market", "Opportunity", "GoalScanner", "ScanResult"]

__version__ = "0.1.0"