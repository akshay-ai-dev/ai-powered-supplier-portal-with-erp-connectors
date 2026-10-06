"""Command-line entry point.

    python main.py --input-dir data --output-dir outputs_shipments
    python main.py --input-dir data --output-dir outputs_shipments --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.batch import run_batch


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract six shipment fields (shipDate, carrier, trackingNumbers, shippedQuantity, lotNumbers, serialNumbers) from images into JSON files using the OpenAI API."
    )
    parser.add_argument("--input-dir", type=Path, default=Path("data"),
                        help="folder searched recursively for images (default: data)")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs_shipments"),
                        help="folder where JSON results are written (default: outputs_shipments)")
    parser.add_argument("--dry-run", action="store_true",
                        help="list and check images without calling the API (no key needed)")
    parser.add_argument("--overwrite", action="store_true",
                        help="reprocess images that already have a successful result")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run_batch(args.input_dir, args.output_dir, overwrite=args.overwrite, dry_run=args.dry_run)
    except KeyboardInterrupt:
        print("\nInterrupted. Completed results were saved; rerun to continue (they will be skipped).")
        return 130


if __name__ == "__main__":
    sys.exit(main())
