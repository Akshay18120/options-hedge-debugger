"""Portable HTML and CSV reports. No network assets or browser dependencies."""
import csv
from html import escape
from pathlib import Path


def money(x):
    return f"{x:,.2f}"


def table(headers, rows):
    return '<table><thead><tr>' + ''.join(f'<th>{escape(str(x))}</th>' for x in headers) + '</tr></thead><tbody>' + ''.join(
        '<tr>' + ''.join(f'<td>{escape(str(x))}</td>' for x in row) + '</tr>' for row in rows) + '</tbody></table>'


def sparkline(trace):
    values = [0.0] + [r['pnl'] for r in trace]
    low, high = min(values), max(values)
    width, height = 800, 160
    scale = max(high - low, 1)
    points = ' '.join(f'{20+i*(width-40)/(len(values)-1):.2f},{20+(high-v)*(height-40)/scale:.2f}' for i, v in enumerate(values))
    zero = 20 + high * (height-40) / scale
    return f'''<svg viewBox="0 0 {width} {height}" role="img" aria-label="Marked profit and loss along this stress path, from inception to horizon">
    <line x1="20" x2="780" y1="{zero:.2f}" y2="{zero:.2f}" stroke="#9aa8b2" stroke-dasharray="4"/>
    <polyline fill="none" stroke="#126b66" stroke-width="2.5" points="{points}"/>
    <text x="20" y="12">High {money(high)}</text><text x="570" y="150">Low {money(low)} · time →</text></svg>'''


def write_report(result, folder: Path):
    summaries = result['summaries']
    body = '''<p class="eyebrow">OPTIONS HEDGE DEBUGGER / RESEARCH REPORT</p>
    <h1>Find the failure.<br>Understand the hedge.</h1>
    <p class="lead">A finite stress search across hypothetical price paths, volatility shocks, liquidity costs and hedge outages.</p>
    <p>All amounts use the same currency unit as the input prices. These scenarios have no assigned probabilities. The lowest P&amp;L below is the worst <em>among the evaluated paths</em>, not a bound on possible losses.</p>'''
    m = result['market']
    body += f"<h2>Experiment</h2><p>{result['scenario_count']} paths × 3 policies · {m['horizon_days']} calendar days · initial spot {money(m['spot'])}</p>"
    body += table(['Symbol', 'Type', 'Strike', 'Days to expiry', 'Contracts', 'Multiplier', 'Initial IV'],
                  [(p['symbol'], p['kind'], p['strike'], p['maturity_days'], p['contracts'], p['multiplier'], f"{p['iv']:.1%}") for p in result['positions']])
    body += '<h2>Worst evaluated outcome per policy</h2><p>Each row can refer to a different scenario. Use the matched-scenario section below for direct policy comparisons.</p>'
    body += table(['Policy', 'Lowest P&L', 'Maximum costs across grid', 'Worst scenario'],
                  [(s['policy'], money(s['worst_pnl']), money(s['max_cost']), s['worst_scenario']) for s in summaries])
    worst = min(result['results'], key=lambda r: r['pnl'])
    matched = [r for r in result['results'] if r['scenario'] == worst['scenario']]
    body += '<h2>All policies on the same failure scenario</h2><p>' + escape(worst['scenario_name']) + '</p>'
    body += table(['Policy', 'P&L', 'Costs', 'Hedge trades', 'Maximum drawdown'],
                  [(r['policy'], money(r['pnl']), money(r['costs']), r['trades'], money(r['max_drawdown'])) for r in matched])
    for run in result['worst_runs']:
        body += '<section><h2>' + escape(run['policy']) + ': failure breakdown</h2><p>' + escape(run['scenario_name']) + '</p>'
        body += sparkline(run['trace'])
        body += table(['Exact accounting component', 'Contribution'], [
            ('Option mark change', money(run['option_pnl'])), ('Underlying hedge price P&L', money(run['stock_pnl'])),
            ('Financing', money(run['financing'])), ('Underlying dividends', money(run['dividends'])),
            ('Execution costs', money(-run['costs'])), ('Total', money(run['pnl'])),
            ('Accounting reconciliation residual', f"{run['accounting_residual']:.3g}")])
        attrs = run['option_attribution']
        body += '<h3>Why the option mark changed</h3><p>Local Greek approximations, accumulated over the path. Gamma, vega and theta effects interact under large shocks; the residual is shown explicitly.</p>'
        body += table(['Approximate contribution', 'Amount'], [(k, money(v)) for k, v in attrs.items()])
        dominant = max((k for k in attrs if k != 'residual'), key=lambda k: abs(attrs[k]))
        body += f"<p>The largest absolute Greek contribution was <strong>{dominant}</strong> ({money(attrs[dominant])}). The hedge incurred {money(run['costs'])} in execution costs over {run['trades']} trades.</p>"
        body += table(['Day', 'Spot', 'P&L', 'Hedge shares', 'Net delta before action', 'Costs to date', 'Hedge outage'],
                      [(r['day'], money(r['spot']), money(r['pnl']), money(r['shares']), money(r['delta_before']), money(r['costs']), r['hedge_unavailable']) for r in run['trace']])
        body += '</section>'
    body += '''<h2>How to use the findings</h2>
    <p>Inspect whether losses are dominated by nonlinear option exposure, volatility repricing or repeated hedging costs. Change one assumption at a time and rerun the identical scenario grid. Treat the fixed threshold as a baseline, not a calibrated optimum. Adding a hedge instrument requires a new model and separate evaluation.</p>
    <h2>Model boundaries</h2>
    <ul><li>European options on one underlying, marked with Black–Scholes–Merton. No early exercise, stochastic rates, volatility smile or option bid/ask valuation.</li>
    <li>The option book is held to the horizon. Only underlying shares trade. Their opening and final liquidation costs are included. Fractional shares are permitted.</li>
    <li>Flat borrowing/lending rate; continuous dividend yield paid approximately once per day. Dividends are charged for short shares.</li>
    <li>Daily decision points. Overnight jumps occur before the next rebalance. The initial hedge can trade; outages block days 1 through the specified duration. Final liquidation is assumed available.</li>
    <li>Underlying execution is at spot plus proportional spread and per-share fees. No market impact, partial fills or queue model. Outages represent unavailable hedge opportunities, not calibrated exchange latency.</li>
    <li>IV is floored at 1%. The roundtrip price path returns to its initial spot; volatility can still change. A quote-bounded hedge size can leave residual exposure.</li>
    <li>No historical or live performance claim. Scenario search provides neither probabilities nor confidence levels. Results do not establish an optimal or safe hedge.</li></ul>
    <h2>Reproduce this report</h2><p>The adjacent results.json contains all inputs, every scenario outcome, policy worst-path traces, version metadata and the CSV hash. Run <code>hedge-debugger replay --report results.json --output replay</code> to repeat the experiment.</p>'''
    css = '''body{max-width:1060px;margin:60px auto;padding:0 24px;font:16px/1.65 system-ui,sans-serif;color:#203239;background:#fafbf8}h1{font-size:48px;line-height:1.12;letter-spacing:-1.5px}h2{margin-top:44px;font-size:25px}h3{margin-top:28px}.eyebrow{font-size:12px;font-weight:700;letter-spacing:2px;color:#126b66}.lead{font-size:21px;max-width:760px}table{border-collapse:collapse;width:100%;margin:20px 0;font-size:13px}th,td{text-align:left;padding:11px 9px;border-bottom:1px solid #d9e2dc;vertical-align:top}th{color:#126b66}section{border-top:2px solid #203239;margin-top:50px}svg{width:100%;max-height:190px;background:#eef3ed;border-radius:6px}svg text{font:11px system-ui;fill:#53676b}code{overflow-wrap:anywhere}li{margin:8px 0}@media(max-width:650px){h1{font-size:34px}table{display:block;overflow-x:auto}}@media print{body{margin:0}section{break-before:page}table{font-size:10px}}'''
    html = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Options hedge failure report</title><style>' + css + '</style><body><main>' + body + '</main></body></html>'
    (folder / 'report.html').write_text(html, encoding='utf-8')
    columns = ['policy', 'scenario_name', 'pnl', 'option_pnl', 'stock_pnl', 'financing', 'dividends', 'costs', 'turnover', 'trades', 'max_drawdown', 'max_delta_shares', 'accounting_residual']
    with (folder / 'scenarios.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(result['results'])
