"""Command-line entry point: extract one packing-list PDF to a JSON draft.

    python app.py samples\\pdf-5.pdf
    python app.py samples\\pdf-5.pdf --out outputs\\pdf-5.json --po-qty 42 --po-unit PR --po-item 10Y1532-9.75A

The PO quantity/unit/item come from the user or portal, never from the document.
(No browser UI yet; this stage is extraction and evaluation only.)
"""

import argparse
import json
import sys
from pathlib import Path

from isolation import convert_isolated, is_conversion_error, write_text_atomic
from po_check import compare_po_quantity


def main(argv=None):
    ap = argparse.ArgumentParser(description="Rule-based packing-list extraction (Docling, local only)")
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--out", type=Path, help="write JSON here instead of stdout")
    ap.add_argument("--po-qty", type=float, help="PO quantity supplied by the user/portal")
    ap.add_argument("--po-unit", help="PO unit of measure, e.g. EA, PR, SF")
    ap.add_argument("--po-item", help="PO item/part number to match against shipped lines")
    args = ap.parse_args(argv)

    if not args.pdf.exists():
        ap.error(f"file not found: {args.pdf}")
    # Docling runs in a child process (with one retry) so a native crash cannot take this process down.
    result, _markdown = convert_isolated(args.pdf)
    failed = is_conversion_error(result)
    if args.po_qty is not None and not failed:
        result["poComparison"] = compare_po_quantity(result, args.po_qty, args.po_unit, args.po_item)

    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.out:
        write_text_atomic(args.out, text)
        print(f"wrote {args.out}" + (" (CONVERSION ERROR)" if failed else ""))
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(text)
    if failed:
        print(result["conversionError"]["message"], file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
