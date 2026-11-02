"""Self-financing mark-to-model replay and an explicit, finite stress grid.

The option book is held throughout; only underlying shares are traded. Initial
option value is financed at the configured rate. No profits from trade entry
or option execution are assumed. All paths are hypothetical, not forecasts.
"""
from dataclasses import asdict, dataclass
from itertools import product
from math import exp, sin, pi
from .models import Market, Position, finite
from .pricing import Greeks, price_greeks

POLICIES = ("unhedged", "daily_delta", "threshold_delta")

@dataclass(frozen=True)
class Scenario:
    move: float
    iv_shift: float
    shape: str = "gradual"
    spread_multiplier: float = 1.0
    outage_days: int = 0

    def __post_init__(self):
        finite("move", self.move, -0.8, 2)
        finite("iv_shift", self.iv_shift, -1, 2)
        finite("spread_multiplier", self.spread_multiplier, 1, 100)
        if self.shape not in {"gradual", "gap", "roundtrip"}:
            raise ValueError("Unknown path shape")
        if type(self.outage_days) is not int or not 0 <= self.outage_days <= 365:
            raise ValueError("outage_days must be an integer between 0 and 365")

    @property
    def name(self):
        return (f"{self.shape}: spot {self.move:+.0%}, IV {self.iv_shift:+.0%} absolute, "
                f"spread x{self.spread_multiplier:g}, outage {self.outage_days}d")


def grid():
    # Defined before evaluation. Results are minima over this grid, not a global
    # worst case. +/- 10% IV means 10 volatility percentage points.
    return [Scenario(m, v, shape, spread, outage)
            for m, v, shape, spread, outage in product(
                (-0.20, -0.10, 0.0, 0.10, 0.20), (-0.10, 0.0, 0.20),
                ("gradual", "gap", "roundtrip"), (1.0, 5.0), (0, 3))]


def book(positions: list[Position], spot: float, day: int, shift: float, market: Market) -> Greeks:
    values = [0.0] * 5
    for p in positions:
        g = price_greeks(p.kind, spot, p.strike, max(p.maturity_days - day, 0) / 365,
                         max(p.iv + shift, 0.01), market.rate, market.dividend)
        units = p.contracts * p.multiplier
        for i, key in enumerate(("price", "delta", "gamma", "vega", "theta")):
            values[i] += getattr(g, key) * units
    return Greeks(*values)


def point(scenario: Scenario, day: int, market: Market):
    progress = day / market.horizon_days
    if scenario.shape == "gap":
        factor = float(day > 0)
    elif scenario.shape == "roundtrip":
        factor = sin(pi * progress)
    else:
        factor = progress
    # Volatility shock is applied on day 1 for gap paths, gradually otherwise.
    vol_factor = float(day > 0) if scenario.shape == "gap" else progress
    return market.spot * (1 + scenario.move * factor), scenario.iv_shift * vol_factor


def simulate(positions: list[Position], market: Market, scenario: Scenario, policy: str):
    if policy not in POLICIES:
        raise ValueError("Unknown hedging policy")
    if not positions or len({p.symbol for p in positions}) != 1:
        raise ValueError("Exactly one underlying and at least one position required")
    if any(p.maturity_days < market.horizon_days for p in positions):
        raise ValueError("Every option must mature on or after horizon_days")
    initial = book(positions, market.spot, 0, 0, market)
    cash, shares = -initial.price, 0.0
    costs, stock_pnl, financing, dividends, turnover = 0.0, 0.0, 0.0, 0.0, 0.0
    attribution = dict(delta=0.0, gamma=0.0, vega=0.0, theta=0.0)
    trades, trace = [], []
    peak, max_drawdown, max_exposure = 0.0, 0.0, 0.0
    prev_spot, prev_shift, prev_g = market.spot, 0.0, initial

    def execute(target, spot, day, reason):
        nonlocal cash, shares, costs, turnover
        qty = target - shares
        if abs(qty) < 1e-10:
            return
        cost = abs(qty) * (spot * market.half_spread_bps / 10000 * scenario.spread_multiplier
                           + market.fee_per_share)
        cash -= qty * spot + cost
        shares = target
        costs += cost
        turnover += abs(qty) * spot
        trades.append(dict(day=day, quantity=qty, spot=spot, cost=cost, reason=reason))

    for day in range(market.horizon_days + 1):
        spot, shift = point(scenario, day, market)
        g = book(positions, spot, day, shift, market)
        if day:
            accrual = cash * (exp(market.rate / 365) - 1)
            dividend_cash = shares * prev_spot * market.dividend / 365
            cash += accrual + dividend_cash
            financing += accrual
            dividends += dividend_cash
            ds = spot - prev_spot
            stock_pnl += shares * ds
            attribution["delta"] += prev_g.delta * ds
            attribution["gamma"] += 0.5 * prev_g.gamma * ds**2
            # Per-leg floor must match book valuation; otherwise the vega
            # attribution would wrongly assume an identical shock for every leg.
            attribution["vega"] += sum(
                p.contracts * p.multiplier * price_greeks(
                    p.kind, prev_spot, p.strike, (p.maturity_days - day + 1) / 365,
                    max(p.iv + prev_shift, 0.01), market.rate, market.dividend).vega
                * (max(p.iv + shift, 0.01) - max(p.iv + prev_shift, 0.01))
                for p in positions)
            attribution["theta"] += prev_g.theta / 365
        exposure_before = g.delta + shares
        max_exposure = max(max_exposure, abs(exposure_before))
        outage = 1 <= day <= scenario.outage_days
        if day == market.horizon_days:
            # Final inventory is always liquidated; outage affects intermediate
            # hedge opportunities, not terminal settlement.
            execute(0, spot, day, "terminal liquidation")
        elif policy != "unhedged" and not outage:
            target = max(-market.max_hedge_shares, min(market.max_hedge_shares, -g.delta))
            if day == 0 or policy == "daily_delta" or abs(g.delta + shares) >= market.threshold_shares:
                execute(target, spot, day, "initial hedge" if day == 0 else "rebalance")
        pnl = g.price + shares * spot + cash
        peak = max(peak, pnl)
        max_drawdown = max(max_drawdown, peak - pnl)
        trace.append(dict(day=day, spot=spot, iv_shift=shift, option_value=g.price,
                          shares=shares, cash=cash, pnl=pnl, costs=costs,
                          delta_before=exposure_before, delta_after=g.delta + shares,
                          hedge_unavailable=outage and day < market.horizon_days))
        prev_spot, prev_shift, prev_g = spot, shift, g
    option_pnl = g.price - initial.price
    attribution["residual"] = option_pnl - sum(attribution.values())
    explained = option_pnl + stock_pnl + financing + dividends - costs
    return dict(policy=policy, scenario=asdict(scenario), scenario_name=scenario.name,
                pnl=pnl, option_pnl=option_pnl, stock_pnl=stock_pnl, financing=financing,
                dividends=dividends, costs=costs, turnover=turnover, trades=len(trades),
                max_drawdown=max_drawdown, max_delta_shares=max_exposure,
                accounting_residual=pnl - explained, option_attribution=attribution,
                trace=trace, executions=trades)


def analyze(positions, market, scenarios=None):
    scenarios = list(grid() if scenarios is None else scenarios)
    if not scenarios:
        raise ValueError("At least one scenario required")
    if len(scenarios) > 5000:
        raise ValueError("Scenario grid is limited to 5000 paths")
    results = [simulate(positions, market, s, policy) for s in scenarios for policy in POLICIES]
    summaries = []
    for policy in POLICIES:
        subset = [r for r in results if r["policy"] == policy]
        worst = min(subset, key=lambda r: r["pnl"])
        summaries.append(dict(policy=policy, worst_pnl=worst["pnl"],
                              worst_scenario=worst["scenario_name"],
                              max_cost=max(r["costs"] for r in subset)))
    # Keep detailed traces only for each policy's worst path. Compact records
    # retain every result for same-scenario comparisons and independent review.
    worst_runs = [min((r for r in results if r["policy"] == p), key=lambda r: r["pnl"]) for p in POLICIES]
    compact = [{k: v for k, v in r.items() if k not in {"trace", "executions"}} for r in results]
    return dict(schema_version=1, market=asdict(market), positions=[asdict(p) for p in positions],
                scenario_count=len(scenarios), summaries=summaries,
                worst_runs=worst_runs, results=compact)
