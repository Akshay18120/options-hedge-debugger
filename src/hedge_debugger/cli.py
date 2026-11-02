import argparse
from dataclasses import asdict
import hashlib
from importlib.resources import files
import json
from pathlib import Path
import sys
from . import __version__
from .engine import Scenario, analyze
from .models import Market, Position, load_market, load_positions
from .report import write_report


def emit(result, output):
    output.mkdir(parents=True, exist_ok=True)
    (output / 'results.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    write_report(result, output)
    print(f"Evaluated {result['scenario_count']} hypothetical paths across 3 policies.")
    print(f"Report: {(output / 'report.html').resolve()}")
    print(f"Reproducible inputs and results: {(output / 'results.json').resolve()}")


def main(argv=None):
    parser = argparse.ArgumentParser(description='Find and explain option hedge failures in a bounded hypothetical stress grid.')
    parser.add_argument('--version', action='version', version=__version__)
    commands = parser.add_subparsers(dest='command', required=True)
    demo = commands.add_parser('demo', help='Run a bundled example without API keys')
    demo.add_argument('--output', type=Path, default=Path('hedge-report'))
    run = commands.add_parser('analyze', help='Analyze a CSV position book')
    run.add_argument('--positions', type=Path, required=True)
    run.add_argument('--market', type=Path, required=True)
    run.add_argument('--scenarios', type=Path, help='Optional JSON list of explicit scenarios')
    run.add_argument('--output', type=Path, default=Path('hedge-report'))
    replay = commands.add_parser('replay', help='Re-run the exact input scenarios embedded in results.json')
    replay.add_argument('--report', type=Path, required=True)
    replay.add_argument('--output', type=Path, default=Path('hedge-replay'))
    args = parser.parse_args(argv)
    try:
        if args.command == 'replay':
            original = json.loads(args.report.read_text())
            if original.get('schema_version') != 1:
                raise ValueError('Unsupported report schema')
            if original.get('metadata', {}).get('engine_version') != __version__:
                raise ValueError('Engine version differs; use the version recorded in the report')
            positions = [Position(**p) for p in original['positions']]
            market = Market(**original['market'])
            unique = list(dict.fromkeys(json.dumps(r['scenario'], sort_keys=True) for r in original['results']))
            scenarios = [Scenario(**json.loads(s)) for s in unique]
            metadata = original['metadata']
        else:
            if args.command == 'demo':
                resource = files('hedge_debugger').joinpath('data')
                positions_path = Path(str(resource.joinpath('positions.csv')))
                market_path = Path(str(resource.joinpath('market.json')))
            else:
                positions_path, market_path = args.positions, args.market
            positions, market = load_positions(positions_path), load_market(market_path)
            scenarios = None
            if args.command == 'analyze' and args.scenarios:
                raw = json.loads(args.scenarios.read_text())
                if not isinstance(raw, list):
                    raise ValueError('Scenarios JSON must be a list')
                scenarios = [Scenario(**s) for s in raw]
            metadata = dict(engine_version=__version__, python_version=sys.version.split()[0],
                            positions_sha256=hashlib.sha256(positions_path.read_bytes()).hexdigest(),
                            model='European Black-Scholes-Merton; calendar ACT/365; deterministic daily stress paths')
        result = analyze(positions, market, scenarios)
        result['metadata'] = metadata
        if args.command == 'replay':
            # Do not silently issue a different report if reproduction changes.
            if result['results'] != original['results']:
                raise ValueError('Replay differs from saved results; check Python/platform numerical differences or modified code')
        emit(result, args.output)
    except (OSError, ValueError, TypeError, KeyError, OverflowError) as e:
        parser.exit(2, f'Error: {e}\n')
    return 0

if __name__ == '__main__':
    main()
