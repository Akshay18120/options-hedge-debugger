import json
import math
from pathlib import Path
import tempfile
import unittest
from hedge_debugger.pricing import price_greeks
from hedge_debugger.models import Market, Position, load_positions, load_market
from hedge_debugger.engine import Scenario, analyze, book, grid, simulate
from hedge_debugger.cli import main


class PricingTests(unittest.TestCase):
    def test_known_prices(self):
        self.assertAlmostEqual(price_greeks('call',100,100,1,.2,.05).price,10.450583572,places=7)
        self.assertAlmostEqual(price_greeks('put',100,100,1,.2,.05).price,5.573526022,places=7)

    def test_put_call_parity_with_dividends(self):
        c = price_greeks('call',110,100,.7,.3,.04,.02)
        p = price_greeks('put',110,100,.7,.3,.04,.02)
        self.assertAlmostEqual(c.price-p.price,110*math.exp(-.02*.7)-100*math.exp(-.04*.7))
        self.assertAlmostEqual(c.delta-p.delta,math.exp(-.02*.7))

    def test_greeks_against_independent_finite_differences(self):
        for kind in ('call','put'):
            f = lambda s,t,v: price_greeks(kind,s,105,t,v,.03,.01).price
            g=price_greeks(kind,100,105,.8,.25,.03,.01)
            h=.001
            self.assertAlmostEqual(g.delta,(f(100+h,.8,.25)-f(100-h,.8,.25))/(2*h),places=6)
            self.assertAlmostEqual(g.gamma,(f(100+h,.8,.25)-2*f(100,.8,.25)+f(100-h,.8,.25))/h**2,places=6)
            self.assertAlmostEqual(g.vega,(f(100,.8,.25001)-f(100,.8,.24999))/.00002,places=5)
            self.assertAlmostEqual(g.theta,(f(100,.79999,.25)-f(100,.80001,.25))/.00002,places=5)

    def test_expiry_payoff(self):
        self.assertEqual(price_greeks('call',120,100,0,.2).price,20)
        self.assertEqual(price_greeks('put',80,100,0,.2).price,20)
        self.assertEqual(price_greeks('put',100,100,0,.2).delta,-.5)

    def test_bad_inputs(self):
        for args in [('bad',100,100,1,.2),('call',0,100,1,.2),('call',100,100,-1,.2),('call',100,100,1,float('nan'))]:
            with self.assertRaises(ValueError): price_greeks(*args)


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.positions=[Position('TEST','call',100,30,-10,100,.25),Position('TEST','put',100,30,-10,100,.25)]
        self.market=Market(horizon_days=10)

    def test_exact_accounting_on_every_stress_path(self):
        result=analyze(self.positions,self.market)
        self.assertEqual(result['scenario_count'],180)
        self.assertEqual(len(result['results']),540)
        for r in result['results']:
            self.assertLess(abs(r['accounting_residual']),1e-7)
            a=r['option_attribution']
            self.assertAlmostEqual(sum(a.values()),r['option_pnl'],places=8)
            self.assertGreaterEqual(r['costs'],0)

    def test_unhedged_has_no_hedge_cost_or_pnl(self):
        r=simulate(self.positions,self.market,Scenario(-.2,.2,'gap'), 'unhedged')
        self.assertEqual(r['trades'],0)
        self.assertEqual(r['stock_pnl'],0)
        self.assertEqual(r['costs'],0)

    def test_offsetting_positions_cancel(self):
        positions=[Position('TEST','call',100,30,1,100,.25),Position('TEST','call',100,30,-1,100,.25)]
        r=simulate(positions,self.market,Scenario(.2,.2),'daily_delta')
        self.assertAlmostEqual(r['pnl'],0)
        self.assertEqual(r['trades'],0)

    def test_flat_zero_cost_path_reconciles_to_decay(self):
        m=Market(rate=0,half_spread_bps=0,fee_per_share=0,horizon_days=10)
        r=simulate(self.positions,m,Scenario(0,0),'daily_delta')
        expected=book(self.positions,100,10,0,m).price-book(self.positions,100,0,0,m).price
        self.assertAlmostEqual(r['pnl'],expected,places=8)

    def test_outage_blocks_rebalances_but_not_initial_or_terminal(self):
        r=simulate(self.positions,self.market,Scenario(.2,.2,'gradual',5,3),'daily_delta')
        days=[t['day'] for t in r['executions']]
        self.assertTrue(0 in days and self.market.horizon_days in days)
        self.assertFalse(set(days)&{1,2,3})
        self.assertEqual(r['trace'][-1]['shares'],0)

    def test_jump_is_not_hedged_with_future_knowledge(self):
        r=simulate(self.positions,self.market,Scenario(.2,.2,'gap'),'daily_delta')
        self.assertAlmostEqual(r['executions'][0]['quantity'],-book(self.positions,100,0,0,self.market).delta)
        initial_shares=r['trace'][0]['shares']
        self.assertAlmostEqual(r['trace'][1]['spot'],120)
        # Hedge stock P&L from the initial jump must use the initial shares.
        s=simulate(self.positions,Market(horizon_days=1),Scenario(.2,.2,'gap'),'daily_delta')
        self.assertAlmostEqual(s['stock_pnl'],initial_shares*20)

    def test_threshold_reduces_to_daily_at_zero(self):
        m=Market(horizon_days=10,threshold_shares=0)
        a=simulate(self.positions,m,Scenario(.1,0),'daily_delta')
        b=simulate(self.positions,m,Scenario(.1,0),'threshold_delta')
        self.assertEqual(a['pnl'],b['pnl'])
        self.assertEqual(a['executions'],b['executions'])

    def test_hedge_limit_enforced(self):
        r=simulate(self.positions,Market(max_hedge_shares=5,horizon_days=10),Scenario(.2,0),'daily_delta')
        self.assertTrue(all(abs(t['shares'])<=5 for t in r['trace']))

    def test_expiry_inside_horizon_rejected(self):
        with self.assertRaises(ValueError):
            simulate([Position('T','call',100,1,1,100,.2)],self.market,Scenario(0,0),'unhedged')

    def test_terminal_expiry_supported(self):
        p=[Position('T','call',100,10,1,100,.2)]
        r=simulate(p,self.market,Scenario(.2,0),'daily_delta')
        self.assertAlmostEqual(r['trace'][-1]['option_value'],2000)

    def test_scenario_validation(self):
        for kwargs in [dict(move=-1,iv_shift=0),dict(move=0,iv_shift=0,shape='unknown'),dict(move=0,iv_shift=0,outage_days=1.5)]:
            with self.assertRaises(ValueError): Scenario(**kwargs)


class InputAndCliTests(unittest.TestCase):
    def test_csv_validation_and_market_validation(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'bad.csv'
            p.write_text('symbol,type,strike,maturity_days,contracts,multiplier,iv\nA,call,100,30,1,100,nan\n')
            with self.assertRaisesRegex(ValueError,'line 2'): load_positions(p)
            p.write_text('symbol,type,strike,maturity_days,contracts,multiplier,iv\nA,call,100,30,1,100,.2\nB,put,100,30,1,100,.2\n')
            with self.assertRaisesRegex(ValueError,'one underlying'): load_positions(p)
            p.write_text('{"spot":100,"unknown":1}')
            with self.assertRaisesRegex(ValueError,'Unknown'): load_market(p)

    def test_report_and_replay_end_to_end(self):
        with tempfile.TemporaryDirectory() as t:
            out=Path(t)/'original'; replay=Path(t)/'replayed'
            self.assertEqual(main(['demo','--output',str(out)]),0)
            self.assertEqual(main(['replay','--report',str(out/'results.json'),'--output',str(replay)]),0)
            a=json.loads((out/'results.json').read_text())
            b=json.loads((replay/'results.json').read_text())
            self.assertEqual(a,b)
            self.assertEqual(len((out/'scenarios.csv').read_text().splitlines()),541)
            self.assertIn('Accounting reconciliation residual',(out/'report.html').read_text())
            self.assertNotIn('<script',(out/'report.html').read_text())

    def test_html_escapes_csv_symbols(self):
        from hedge_debugger.report import write_report
        with tempfile.TemporaryDirectory() as t:
            r=analyze([Position('<script>alert(1)</script>','call',100,30,1,100,.2)],Market(horizon_days=1),[Scenario(0,0)])
            write_report(r,Path(t))
            html=(Path(t)/'report.html').read_text()
            self.assertNotIn('<script>',html)
            self.assertIn('&lt;script&gt;',html)


if __name__=='__main__': unittest.main()
