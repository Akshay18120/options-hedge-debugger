"""Black-Scholes-Merton prices and sensitivities, with continuous dividends.

Vega is per 1.0 absolute volatility change; theta is per calendar year.
At expiry, delta uses the midpoint convention at the strike. Other Greeks
are returned as zero because the smooth pre-expiry formula does not apply.
"""
from dataclasses import dataclass
from math import erf, exp, isfinite, log, pi, sqrt

@dataclass(frozen=True)
class Greeks:
    price: float
    delta: float
    gamma: float
    vega: float
    theta: float


def price_greeks(kind: str, spot: float, strike: float, years: float,
                 volatility: float, rate: float = 0.0, dividend: float = 0.0) -> Greeks:
    if kind not in {"call", "put"}:
        raise ValueError("Option type must be call or put")
    values = (spot, strike, years, volatility, rate, dividend)
    if not all(isfinite(x) for x in values):
        raise ValueError("Pricing inputs must be finite")
    if spot <= 0 or strike <= 0 or years < 0 or volatility <= 0:
        raise ValueError("Spot, strike and volatility must be positive; time nonnegative")
    sign = 1 if kind == "call" else -1
    if years == 0:
        delta = (float(spot > strike) + 0.5 * float(spot == strike))
        if kind == "put":
            delta -= 1
        return Greeks(max(sign * (spot - strike), 0.0), delta, 0.0, 0.0, 0.0)
    root_t = sqrt(years)
    d1 = (log(spot / strike) + (rate - dividend + volatility**2 / 2) * years) / (volatility * root_t)
    d2 = d1 - volatility * root_t
    cdf = lambda x: (1 + erf(x / sqrt(2))) / 2
    density = exp(-d1**2 / 2) / sqrt(2 * pi)
    dq, dr = exp(-dividend * years), exp(-rate * years)
    price = sign * (spot * dq * cdf(sign * d1) - strike * dr * cdf(sign * d2))
    delta = sign * dq * cdf(sign * d1)
    gamma = dq * density / (spot * volatility * root_t)
    vega = spot * dq * density * root_t
    theta = (-spot * dq * density * volatility / (2 * root_t)
             - sign * rate * strike * dr * cdf(sign * d2)
             + sign * dividend * spot * dq * cdf(sign * d1))
    return Greeks(price, delta, gamma, vega, theta)
