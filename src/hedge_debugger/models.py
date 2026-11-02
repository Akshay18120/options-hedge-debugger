import csv
import json
from dataclasses import dataclass
from math import isfinite
from pathlib import Path


def finite(name, value, lower=None, upper=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if lower is not None and value < lower:
        raise ValueError(f"{name} must be at least {lower}")
    if upper is not None and value > upper:
        raise ValueError(f"{name} must be at most {upper}")


@dataclass(frozen=True)
class Position:
    symbol: str
    kind: str
    strike: float
    maturity_days: float
    contracts: float
    multiplier: float
    iv: float

    def __post_init__(self):
        if not self.symbol or self.kind not in {"call", "put"}:
            raise ValueError("Each position needs a symbol and call/put type")
        for name in ("strike", "maturity_days", "multiplier", "iv"):
            finite(name, getattr(self, name), 1e-9)
        finite("contracts", self.contracts)


@dataclass(frozen=True)
class Market:
    spot: float = 100.0
    rate: float = 0.03
    dividend: float = 0.0
    horizon_days: int = 20
    half_spread_bps: float = 2.0
    fee_per_share: float = 0.005
    threshold_shares: float = 25.0
    max_hedge_shares: float = 100000.0

    def __post_init__(self):
        finite("spot", self.spot, 1e-9)
        finite("rate", self.rate, -0.5, 1)
        finite("dividend", self.dividend, 0, 1)
        if type(self.horizon_days) is not int or not 1 <= self.horizon_days <= 365:
            raise ValueError("horizon_days must be an integer between 1 and 365")
        for name in ("half_spread_bps", "fee_per_share", "threshold_shares"):
            finite(name, getattr(self, name), 0)
        finite("max_hedge_shares", self.max_hedge_shares, 1e-9)


def load_market(path: Path) -> Market:
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError("Market configuration must be a JSON object")
    unknown = set(raw) - set(Market.__dataclass_fields__)
    if unknown:
        raise ValueError(f"Unknown market fields: {', '.join(sorted(unknown))}")
    return Market(**raw)


def load_positions(path: Path) -> list[Position]:
    columns = {"symbol", "type", "strike", "maturity_days", "contracts", "multiplier", "iv"}
    positions = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if len(reader.fieldnames or []) != len(columns) or set(reader.fieldnames or []) != columns:
            raise ValueError("CSV columns must be: " + ",".join(sorted(columns)))
        for line, row in enumerate(reader, 2):
            if len(positions) >= 1000:
                raise ValueError("CSV is limited to 1000 positions")
            try:
                positions.append(Position(row["symbol"].strip(), row["type"].strip().lower(),
                    *(float(row[k]) for k in ("strike", "maturity_days", "contracts", "multiplier", "iv"))))
            except (ValueError, TypeError, AttributeError) as e:
                raise ValueError(f"CSV line {line}: {e}") from e
    if not positions:
        raise ValueError("CSV must contain at least one position")
    if len({p.symbol for p in positions}) != 1:
        raise ValueError("Version 0.1 supports exactly one underlying symbol")
    return positions
