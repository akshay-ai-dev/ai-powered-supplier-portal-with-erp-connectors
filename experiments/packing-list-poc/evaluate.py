"""Run the extractor on every sample PDF and compare against expected labels.

    python evaluate.py                     # samples\\pdf-*.pdf vs expected\\pdf-*.json
    python evaluate.py --samples samples --expected expected --out outputs

Writes outputs\\extractions\\<name>.json (the JSON draft), outputs\\docling\\<name>.md
(Docling's markdown, for reviewing what the converter saw) and outputs\\evaluation_report.json.

Expected files hold a list of checks. Each check is marked "verified": true only when a
person has confirmed it against the PDF; proposed labels stay "verified": false and are
reported separately. No accuracy percentage is printed: counts only.

Check kinds:  {"field", "expected": value}       exact value (lists compared as sets/multisets)
              {"field", "minCount": n}           at least n values
              {"field", "contains": value}       value present in a list
              {"field", "expectReview": true}    extractor must raise a 'review' issue on the field
                                                 (optionally whose raw value contains "rawContains")
Outcomes:     CORRECT, INCORRECT, MISSING (expected a value, got none),
              AMBIGUOUS (value correctly flagged for supplier review instead of asserted).
"""

import argparse
import json
import time
from pathlib import Path


def read_json(path):
    raw = Path(path).read_bytes()
    # Windows PowerShell may save redirected output as UTF-16.
    encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    return json.loads(raw.decode(encoding))


SET_FIELDS = {"trackingNumbers", "lotNumbers", "serialNumbers", "sublotNumbers", "salesOrders"}
MULTISET_FIELDS = {"sublotQuantities", "itemLines"}


def view(ex, field):
    """Value of a (possibly derived) field from an extraction, in canonical form."""
    if field in ("trackingNumbers", "lotNumbers", "serialNumbers"):
        return sorted(ex.get(field) or [])
    subs = ex.get("sublots") or []
    items = ex.get("items") or []
    if field == "sublotNumbers":
        return sorted(s["sublotNumber"] for s in subs)
    if field == "sublotQuantities":
        return sorted((float(s["quantity"]) if s["quantity"] is not None else None, s["unit"]) for s in subs)
    if field == "sublotCount":
        return len(subs)
    if field == "sublotTotal":
        if not subs or any(s["quantity"] is None for s in subs):
            return None
        units = {s["unit"] for s in subs}
        return [round(sum(s["quantity"] for s in subs), 6), units.pop() if len(units) == 1 else None]
    if field == "itemLineCount":
        return len(items)
    if field == "itemLines":
        return sorted((it.get("salesOrder"), it.get("itemNumber"),
                       float(it["quantityShipped"]) if it.get("quantityShipped") is not None else None)
                      for it in items)
    if field == "salesOrders":
        sos = {it["salesOrder"] for it in items if it.get("salesOrder")}
        if not sos:
            sos = {r["value"] for r in (ex.get("references") or {}).get("salesOrders", [])}
        return sorted(sos)
    if field.startswith("references."):
        return sorted(r["value"] for r in (ex.get("references") or {}).get(field.split(".", 1)[1], []))
    if "." in field:
        head, tail = field.split(".", 1)
        return (ex.get(head) or {}).get(tail)
    return ex.get(field)


def canonical(field, value):
    if value is None:
        return None
    if field in SET_FIELDS:
        return sorted(value)
    if field in MULTISET_FIELDS:
        return sorted(tuple(float(x) if isinstance(x, (int, float)) else x for x in v) for v in value)
    if field == "sublotTotal":
        return [round(float(value[0]), 6), value[1]]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return round(float(value), 6)
    return value


def _empty(v):
    return v is None or v == [] or v == ""


def review_issues(ex, field, raw_contains=None):
    out = []
    for iss in ex.get("fieldIssues", []):
        if iss["field"] != field or iss["severity"] != "review":
            continue
        if raw_contains and raw_contains not in str(iss.get("rawValue", "")) + iss["message"]:
            continue
        out.append(iss)
    return out


def run_check(ex, chk):
    field = chk["field"]
    actual = view(ex, field)
    flagged = bool(review_issues(ex, field))
    if chk.get("expectReview"):
        hits = review_issues(ex, field, chk.get("rawContains"))
        status = "AMBIGUOUS" if hits else "INCORRECT"
        exp_txt = f"review flag{' on ' + repr(chk['rawContains']) if chk.get('rawContains') else ''}"
        act_txt = hits[0]["code"] if hits else "not flagged"
        return status, exp_txt, act_txt, flagged
    if "minCount" in chk:
        n = len(actual or [])
        status = "CORRECT" if n >= chk["minCount"] else ("MISSING" if n == 0 else "INCORRECT")
        return status, f">= {chk['minCount']} values", f"{n} values", flagged
    if "contains" in chk:
        status = "CORRECT" if chk["contains"] in (actual or []) else ("MISSING" if _empty(actual) else "INCORRECT")
        return status, f"contains {chk['contains']!r}", actual, flagged
    exp = canonical(field, chk["expected"])
    act = canonical(field, actual)
    if exp == act:
        status = "CORRECT"
    elif _empty(act) and not _empty(exp):
        status = "MISSING"
    else:
        status = "INCORRECT"
    return status, chk["expected"], actual, flagged


def short(v, n=70):
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    return s if len(s) <= n else s[: n - 3] + "..."


def run_evaluation(pdfs, expected_dir, out_dir, convert=None):
    """Convert and score each PDF. Each conversion runs in its own child process (isolation.py);
    a PDF whose conversion fails twice is reported as a conversion error and the loop continues."""
    from isolation import convert_isolated, is_conversion_error, write_json_atomic, write_text_atomic

    convert = convert or (lambda pdf: convert_isolated(pdf, log_dir=out_dir / "logs"))
    (out_dir / "extractions").mkdir(parents=True, exist_ok=True)
    (out_dir / "docling").mkdir(parents=True, exist_ok=True)

    run_start = time.perf_counter()
    report = {"documents": [], "conversionErrors": []}
    totals = {"verified": {}, "unverified": {}}
    for pdf in pdfs:
        result, markdown = convert(pdf)
        ok_path = out_dir / "extractions" / f"{pdf.stem}.json"
        err_path = out_dir / "extractions" / f"{pdf.stem}.conversion-error.json"
        if is_conversion_error(result):
            write_json_atomic(err_path, result)
            for stale in (ok_path, out_dir / "docling" / f"{pdf.stem}.md"):
                if stale.exists():  # an older success in this folder must not pass for this run's result
                    stale.unlink()
            err = result["conversionError"]
            print(f"\n=== {pdf.name}  CONVERSION ERROR: {err['message']}")
            for a in err["attempts"]:
                print(f"    attempt {a['attempt']}: {a['status']} ({a['reason']}) after {a['seconds']}s")
            report["conversionErrors"].append({"sourceFile": pdf.name, "attempts": err["attempts"]})
            report["documents"].append({"sourceFile": pdf.name, "status": "conversion_error",
                                        "checks": [], "counts": {}})
            continue
        if err_path.exists():
            err_path.unlink()
        if markdown is not None:
            write_text_atomic(out_dir / "docling" / f"{pdf.stem}.md", markdown)
        write_json_atomic(ok_path, result)

        tm = result["timings"]
        iso = tm.get("isolation", {})
        retry_note = f"  attempts={iso.get('attemptCount')}" if iso.get("attemptCount", 1) > 1 else ""
        print(f"\n=== {pdf.name}  pages={result['document']['pageCount']}  "
              f"conversion={tm['conversionSeconds']:.1f}s  extraction={tm['extractionSeconds']:.2f}s  "
              f"total={tm['totalSeconds']:.1f}s{retry_note}")
        doc_rep = {"sourceFile": pdf.name, "status": "converted", "timings": tm, "checks": [], "counts": {}}
        exp_path = expected_dir / f"{pdf.stem}.json"
        if not exp_path.exists():
            print(f"  (no expected file {exp_path}; extraction saved, not scored)")
        else:
            for chk in read_json(exp_path)["checks"]:
                status, exp_v, act_v, flagged = run_check(result, chk)
                group = "verified" if chk.get("verified") else "unverified"
                totals[group][status] = totals[group].get(status, 0) + 1
                doc_rep["counts"].setdefault(group, {}).setdefault(status, 0)
                doc_rep["counts"][group][status] += 1
                doc_rep["checks"].append({"field": chk["field"], "status": status, "verified": chk.get("verified", False),
                                          "expected": exp_v, "extracted": act_v, "flaggedForReview": flagged,
                                          "basis": chk.get("basis")})
                mark = "V" if chk.get("verified") else "u"
                flag = " [flagged]" if flagged and status != "AMBIGUOUS" else ""
                print(f"  {status:9} {mark} {chk['field']:<36} expected={short(exp_v, 50)}  "
                      f"extracted={short(act_v, 60)}{flag}")
            for group in ("verified", "unverified"):
                c = doc_rep["counts"].get(group, {})
                print(f"  {group:10}: correct={c.get('CORRECT', 0)} incorrect={c.get('INCORRECT', 0)} "
                      f"missing={c.get('MISSING', 0)} ambiguous={c.get('AMBIGUOUS', 0)}")
        reviews = [i for i in result["fieldIssues"] if i["severity"] == "review"]
        print(f"  issues for supplier review: {len(reviews)}")
        for i in reviews:
            print(f"    - {i['field']}.{i['code']}: {short(i['message'], 120)}")
        report["documents"].append(doc_rep)

    total_runtime = time.perf_counter() - run_start
    report["totals"] = totals
    report["totalRuntimeSeconds"] = round(total_runtime, 3)
    write_json_atomic(out_dir / "evaluation_report.json", report)
    print("\n=== Summary (counts only; 'unverified' labels are proposals awaiting human confirmation)")
    for group in ("verified", "unverified"):
        c = totals[group]
        print(f"  {group:10}: correct={c.get('CORRECT', 0)} incorrect={c.get('INCORRECT', 0)} "
              f"missing={c.get('MISSING', 0)} ambiguous={c.get('AMBIGUOUS', 0)}")
    converted = [d for d in report["documents"] if d["status"] == "converted"]
    conv = sum(d["timings"]["conversionSeconds"] for d in converted)
    print(f"  converted {len(converted)}/{len(pdfs)} PDFs | conversion errors: "
          f"{[e['sourceFile'] for e in report['conversionErrors']] or 'none'}")
    print(f"  Docling conversion {conv:.1f}s | total runtime {total_runtime:.1f}s "
          f"(each PDF loads the models in its own process)")
    print(f"  saved: {out_dir / 'extractions'}, {out_dir / 'docling'}, {out_dir / 'evaluation_report.json'}")
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=Path, default=Path("samples"))
    ap.add_argument("--expected", type=Path, default=Path("expected"))
    ap.add_argument("--out", type=Path, default=Path("outputs"))
    args = ap.parse_args()
    pdfs = sorted(args.samples.glob("pdf-*.pdf"), key=lambda p: (len(p.stem), p.stem))
    if not pdfs:
        raise SystemExit(f"no pdf-*.pdf files in {args.samples}")
    report = run_evaluation(pdfs, args.expected, args.out)
    return 1 if report["conversionErrors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
