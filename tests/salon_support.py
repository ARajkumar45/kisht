"""Constants for the old salon tests (removed with the receptionist package in step 4)."""
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
SALON = Path(__file__).resolve().parent.parent / "businesses" / "glow-salon.yaml"
