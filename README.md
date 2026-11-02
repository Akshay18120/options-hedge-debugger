# Options Hedge Debugger

Find how an option hedge fails, explain the loss, and reproduce the experiment.

This local Python tool imports a European option book, evaluates three hedge policies against the same hypothetical stress scenarios, and produces a portable HTML report with exact P&L reconciliation and an approximate Greek breakdown. It runs without an account, API key, network connection or third-party runtime dependency.

## Quick start

Requires Python 3.10 or later. From this directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
hedge-debugger demo --output hedge-report
```

Open `hedge-report/report.html` in any browser. The bundled short straddle is fictitious; it is an example, not a proposed trade.

## Use your own positions

```bash
hedge-debugger analyze --positions examples/positions.csv --market examples/market.json --output my-report
```

CSV schema:

```csv
symbol,type,strike,maturity_days,contracts,multiplier,iv
DEMO,call,100,30,-10,100,0.25
DEMO,put,100,30,-10,100,0.25
```

- `contracts`: signed quantity; negative means short.
- `multiplier`: underlying units per contract. Do not assume all contracts use 100.
- `iv`: annualized implied volatility in decimal units, so `0.25` means 25%.
- `maturity_days`: calendar days, using ACT/365. All options must expire on or after the experiment horizon.
- All rows must refer to the same underlying and currency. European exercise only; do not import American options as equivalent.
- Input holdings are marked at the model price. The tool does not infer cost basis, accrued returns or executable option prices from the CSV.

The market JSON controls initial spot, constant annual rate and dividend yield, calendar horizon, underlying half-spread in basis points, fee per share, threshold in net delta shares and maximum absolute hedge inventory. The same configured borrowing/lending rate is used. Fractions of shares are permitted.

## Stress search

The default grid evaluates 180 scenarios and 540 policy/scenario combinations:

- Spot moves: -20%, -10%, 0%, +10%, +20%.
- Additive IV shocks: -10, 0, +20 volatility percentage points, floored at 1% IV per leg.
- Paths: gradual, immediate gap, and roundtrip (returns to initial spot).
- Underlying spread multipliers: 1 and 5.
- Missed hedge opportunities on days 1–3: absent or present.

These are chosen stress assumptions with no probabilities. Many paths duplicate economic outcomes when shocks are zero; the count is a scenario grid size, not independent observations. No minimum from this grid is a global worst-case loss estimate.

Custom scenarios:

```bash
hedge-debugger analyze --positions examples/positions.csv --market examples/market.json --scenarios examples/scenarios.json --output custom-report
```

Each scenario takes `move`, `iv_shift`, `shape`, `spread_multiplier`, and `outage_days`. Allowed shapes are `gradual`, `gap`, and `roundtrip`. The initial hedge is placed before day 1, so it cannot use knowledge of a subsequent gap. A final underlying liquidation is always assumed possible, even if the horizon falls in an outage.

## Policies

- `unhedged`: hold the option book and finance its initial value; trade no shares.
- `daily_delta`: rebalance to offset option delta at each available daily decision point.
- `threshold_delta`: open an initial delta hedge, then rebalance only if absolute net delta reaches the specified shares threshold.

All policies see the current scenario IV at the decision time and use the same pricing model as the option marks. This is a simplifying assumption, not a model-misspecification experiment. The share cap can leave residual delta exposure. Policy thresholds are fixed in advance; the tool does not optimize or recommend a hedge after seeing future outcomes.

## Understanding the report

`results.json` stores inputs, package version, Python version, input CSV SHA-256, all compact scenario outcomes and detailed traces for each policy's worst evaluated path. `scenarios.csv` supports independent analysis in a spreadsheet or notebook.

The accounting identity is:

```text
P&L = change in option marks + stock price P&L + cash financing
      + underlying dividend cash flows - hedge execution costs
```

Option marks are revalued exactly within the chosen model. Local delta, gamma, vega and theta approximations explain their change; higher-order interactions and discrete-step error remain in the explicitly reported residual. A large residual is meaningful, especially for gap scenarios. It must not be hidden or called exact Greek attribution.

Worst outcomes for different policies can occur on different scenarios. The report also compares all policies on one identical failure scenario. Maximum drawdown is measured on the daily marked path, including opening costs, from starting P&L zero. It misses intraday changes.

## Reproduction

```bash
hedge-debugger replay --report hedge-report/results.json --output hedge-replay
```

Replay re-evaluates the embedded inputs and scenarios, checks package version, and rejects differing results rather than silently claiming reproduction. Exact floating-point equality may vary across Python/platform math libraries. The package version should be increased when model logic changes. Keep the source revision with research results.

## Tests

```bash
python -m unittest discover -s tests -v
```

Tests check known prices, put-call parity, finite-difference Greeks, terminal payoffs, cash accounting, offsetting books, trade timing without future information, outages, inventory limits, threshold equivalence, input validation, HTML escaping and complete report reproduction.

## Model boundaries

This release is a stress-testing and educational research tool, not a broker-connected execution or margin system. It supports European options on a single underlying with Black–Scholes–Merton marks, fixed rates, parallel IV shocks and deterministic daily spot paths. It has no volatility smile calibration, early exercise, option spreads, market impact, queue effects or partial fills. Dividend cash flows approximate continuous yield once daily. Stress paths are hypothetical and may be inconsistent with a calibrated stochastic market model.

Data never leaves the local process. Reports contain the supplied positions: share example reports intentionally. No WorldQuant platform data, expressions, results or proprietary code are used.

## Research roadmap

1. Validate accounting and hedge baseline behavior — implemented in v0.1.
2. Add separate realized-market and hedge-model dynamics to study model misspecification.
3. Compare fair, separately calibrated hedge rules on held-out simulated regimes.
4. Add appropriately licensed historical quote replay only after checking data quality.

The interesting research contribution is whether observed hedge improvements survive model error and stronger baselines. Version 0.1 provides the reliable experiment foundation; it has not established a new profitable strategy or superior learned hedge.

## References and attribution

- Black–Scholes–Merton formulas are implemented locally; no pricing library code is copied.
- [Deep Hedging, Buehler et al.](https://arxiv.org/abs/1802.03042) motivates the later hedging-policy research. This release does not implement a learned policy.
- [PFHedge](https://github.com/pfnet-research/pfhedge) is an existing deep hedging framework and a possible later benchmark; it is not bundled or required.

## Contributing

See CONTRIBUTING.md. Small reproducible model or accounting counterexamples are particularly welcome.

## License

MIT. See LICENSE.
