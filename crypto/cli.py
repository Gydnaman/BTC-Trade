"""Fail-closed command line entry point for crypto research."""
import argparse
import json
from pathlib import Path
import sys

from crypto.config import load_config
from crypto.data import collect_snapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="UTF-8 JSON research config")
    parser.add_argument("--collect", action="store_true",
                        help="download public market data and write an audited snapshot")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
    except (OSError, ValueError) as exc:
        print(f"Crypto research configuration error: {exc}", file=sys.stderr)
        return 2

    if args.collect:
        try:
            result = collect_snapshot(config)
        except Exception as exc:
            print(f"Crypto data collection failed: {exc}", file=sys.stderr)
            return 2
        manifest = result.get("manifest", {})
        if manifest.get("status") != "audited":
            print(f"Snapshot audit failed: {manifest.get('audit', {}).get('errors', [])}",
                  file=sys.stderr)
            return 1
        print(f"Audited snapshot {manifest.get('snapshot_id')} saved to "
              f"{result.get('manifest_path')}")
        return 0

    manifest_path = Path(config["data"]["root"]) / "manifest.json"
    if not manifest_path.is_file():
        print(f"No audited market-data manifest found: {manifest_path}", file=sys.stderr)
        return 2
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"Market-data manifest error: {exc}", file=sys.stderr)
        return 2
    if not isinstance(manifest, dict) or manifest.get("status") != "audited":
        print("Market-data manifest status must be audited", file=sys.stderr)
        return 2

    print(f"Crypto research inputs accepted: {manifest.get('snapshot_id', 'unknown snapshot')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
