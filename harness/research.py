"""Bounded development experiments. No holdout evaluation or live execution."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform

import numpy as np
import pandas as pd

from backtest.backtester import Backtester
from config.settings import BacktestConfig
from strategy.ma_cross import MACrossStrategy
from strategy.momentum import MomentumStrategy
from strategy.bollinger import BollingerStrategy
from harness.validate import ROOT, run_suite

STRATEGIES = {'ma_cross': MACrossStrategy, 'momentum': MomentumStrategy,
              'bollinger': BollingerStrategy}


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def run_experiment(prices: pd.DataFrame, strategy: str, params: dict,
                   output: Path, max_trials: int = 10) -> dict:
    if strategy not in STRATEGIES or not isinstance(max_trials, int) or not 1 <= max_trials <= 10:
        raise ValueError('Use a registered strategy and a trial budget between 1 and 10')
    if (prices.empty or len(prices) < 2 or not isinstance(prices.index, pd.DatetimeIndex)
            or prices.index.hasnans or prices.index.has_duplicates
            or not prices.index.is_monotonic_increasing or prices.columns.has_duplicates):
        raise ValueError('Need at least two rows, unique sorted dates and unique assets')
    prices = prices.astype(float)
    if not np.isfinite(prices.to_numpy()).all() or (prices <= 0).any().any():
        raise ValueError('Prices must be finite and positive')
    # Fixed illustrative development assumptions, not a market fee schedule.
    config = BacktestConfig(initial_capital=1_000_000, commission_rate=.0003,
                            slippage=.001, stamp_duty=0, risk_free_rate=.025)
    protected = sorted(p for folder in ['backtest', 'config', 'indicators', 'harness', 'tests']
                       for p in (ROOT / folder).glob('*.py'))
    contract = {'data_hash': digest(prices.to_csv().encode()), 'config': asdict(config),
                'max_trials': max_trials, 'stage': 'development_only',
                'python': platform.python_version(), 'pandas': pd.__version__, 'numpy': np.__version__,
                'evaluator_hash': digest(b''.join(str(p.relative_to(ROOT)).encode() + p.read_bytes()
                                                  for p in protected))}
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    lock = output / '.running'
    try:
        handle = lock.open('x')
    except FileExistsError as exc:
        raise ValueError('Experiment is busy; inspect .running after an interrupted process') from exc
    try:
        handle.close()
        manifest = output / 'contract.json'
        if manifest.exists():
            if json.loads(manifest.read_text(encoding='utf-8')) != contract:
                raise ValueError('Evaluation contract changed; use a separate experiment directory')
        else:
            manifest.write_text(json.dumps(contract, indent=2), encoding='utf-8')
        trials = list(output.glob('trial-*.json'))
        if len(trials) >= max_trials:
            raise ValueError('Trial budget exhausted; stop and review the experiment')
        instance = STRATEGIES[strategy](**params)
        if strategy == 'momentum':
            signals = instance.generate_signals(prices)
        else:
            if len(prices.columns) != 1:
                raise ValueError('Single-asset strategies require one price column')
            signals = instance.generate_signals(prices.rename(columns={prices.columns[0]: 'close'}))
            signals.columns = prices.columns
        values = signals.to_numpy(dtype=float)
        if (not np.isfinite(values).all() or (values < 0).any()
                or (signals.sum(axis=1) > 1 + 1e-9).any()):
            raise ValueError('Development contract requires finite long-only weights, gross <= 1')
        result = Backtester(config).run(prices, signals)
        record = {**contract, 'status': 'development_only', 'trial': len(trials) + 1,
                  'created_at': datetime.now(timezone.utc).isoformat(),
                  'strategy': strategy, 'params': instance.params,
                  'strategy_hash': digest((ROOT / 'strategy' / f'{strategy}.py').read_bytes()),
                  'metrics': result.metrics, 'dates': prices.index.astype(str).tolist(),
                  'nav': result.portfolio_value.tolist(),
                  'daily_returns': result.daily_returns.tolist()}
        path = output / f'trial-{record["trial"]:03d}.json'
        with path.open('x', encoding='utf-8') as stream:
            json.dump(record, stream, ensure_ascii=False, indent=2, allow_nan=False)
        return record
    finally:
        lock.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prices', type=Path, required=True, help='Development CSV: date,A[,B...]')
    parser.add_argument('--strategy', choices=STRATEGIES, default='ma_cross')
    parser.add_argument('--params', default='{}', help='JSON strategy constructor parameters')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--max-trials', type=int, default=10)
    args = parser.parse_args()
    validation = run_suite(ROOT / 'tests')
    if not validation['passed']:
        print(validation['output'])
        raise SystemExit(1)
    prices = pd.read_csv(args.prices, index_col='date', parse_dates=['date'])
    record = run_experiment(prices, args.strategy, json.loads(args.params), args.output, args.max_trials)
    print(json.dumps({k: record[k] for k in ['trial', 'status', 'metrics']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
