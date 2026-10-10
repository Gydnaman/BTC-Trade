"""Run offline regression contracts and persist machine-readable evidence."""
import argparse
import io
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def run_suite(test_dir: Path) -> dict:
    stream = io.StringIO()
    suite = unittest.TestLoader().discover(str(test_dir))
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    return {'passed': result.wasSuccessful() and result.testsRun > 0,
            'tests': result.testsRun, 'failures': len(result.failures),
            'errors': len(result.errors), 'output': stream.getvalue()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'results/validation.json')
    args = parser.parse_args()
    report = run_suite(ROOT / 'tests')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(report['output'])
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
