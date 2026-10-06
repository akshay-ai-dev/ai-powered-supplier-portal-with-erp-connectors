"""Unit tests for the extraction rules. They use synthetic layouts (positioned text lines),
so they run in a second without Docling or the sample PDFs.

    .venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from extractor import extract_from_layout  # noqa: E402
from fields import (  # noqa: E402
    classify_identifier, clean_lot_value, label_type, normalize_carrier, normalize_unit, parse_date,
    parse_quantity_with_unit, split_composite_lot, split_freight_terms,
)
from layout import Layout, Line, Page, Word, classify_pages, link_words  # noqa: E402
from po_check import compare_po_quantity  # noqa: E402

CW, H = 5.0, 8.0  # synthetic character width / line height


def ln(text, x, y, page=1):
    line = Line(text, page, x, y, x + CW * len(text), y + H)
    pos = x
    for tok in text.split(" "):
        line.words.append(Word(tok, page, pos, y, pos + CW * len(tok), y + H))
        pos += CW * (len(tok) + 1)
    return line


def layout(*pages):
    built = []
    for i, lines in enumerate(pages, start=1):
        for item in lines:
            for w in item.words:
                w.page = i
            item.page = i
        built.append(Page(i, 612, 792, list(lines), [w for item in lines for w in item.words]))
    classify_pages(built)
    return Layout("synthetic.pdf", built, len(built), text_layer=True, ocr_used=False)


TITLE = ln("PACKING LIST", 250, 40)


def item_header(y=300):
    return [ln("Item Number", 40, y), ln("Unit", 200, y), ln("Ordered", 300, y), ln("Shipped", 400, y)]


def item_row(item, unit, ordered, shipped, y):
    return [ln(item, 40, y), ln(unit, 200, y), ln(ordered, 300, y), ln(shipped, 400, y)]


class IdentifierClassification(unittest.TestCase):
    def test_order_invoice_shipping_numbers_are_not_tracking(self):
        for label, expected in [("Order #", "sales_order"), ("Sales Order No.", "sales_order"),
                                ("Invoice No", "invoice"), ("Shipping Number", "internal_shipping"),
                                ("Packing Slip No", "packing_slip"), ("PO Number", "purchase_order"),
                                ("Load ID No", "internal_shipping")]:
            cls = classify_identifier("775101717550", label=label)
            self.assertEqual(cls["type"], expected, label)
            self.assertFalse(cls["isTracking"], label)

    def test_tracking_column_value(self):
        cls = classify_identifier("775101717550", column_header="Tracking Number", carrier="FedEx")
        self.assertTrue(cls["isTracking"])
        self.assertFalse(cls["ambiguous"])

    def test_tracking_format_conflicting_with_carrier_is_flagged(self):
        cls = classify_identifier("1Z999AA10123456784", column_header="Tracking Number", carrier="FedEx")
        self.assertTrue(cls["isTracking"])
        self.assertTrue(cls["ambiguous"])

    def test_carrier_hash_number_with_wrong_format_is_ambiguous_not_tracking(self):
        cls = classify_identifier("149752137", label="FED EX")
        self.assertFalse(cls["isTracking"])
        self.assertTrue(cls["ambiguous"])

    def test_freight_terms_and_package_count(self):
        self.assertEqual(classify_identifier("Collect")["type"], "freight_terms")
        self.assertEqual(label_type("Number of Packages"), "package_count")
        self.assertEqual(split_freight_terms("DPL/LOGIFISH FREIGHT Collect"), ("DPL/LOGIFISH", "FREIGHT COLLECT"))

    def test_po_box_is_not_a_purchase_order_label(self):
        self.assertIsNone(label_type("PO BOX"))

    def test_lot_values(self):
        self.assertEqual(clean_lot_value("Rf: 9399"), ("9399", None))
        self.assertEqual(clean_lot_value("LOT:2401"), ("2401", None))
        lot, problem = clean_lot_value("(280)")
        self.assertIsNone(lot)
        self.assertIn("parenthesised", problem)
        self.assertEqual(split_composite_lot("US310197LOT2401"), ("US310197", "2401"))
        self.assertEqual(split_composite_lot("6446-0001"), ("6446-0001", None))

    def test_carrier_normalisation(self):
        self.assertEqual(normalize_carrier("FDX 2Day")[:2], ("FedEx", "2DAY"))
        self.assertEqual(normalize_carrier("UPSGND")[0], "UPS")
        self.assertEqual(normalize_carrier("COLLECTION - COLLECTION"), (None, None, "customer_collection"))

    def test_document_level_identifier_separation(self):
        lay = layout([TITLE, ln("Order #", 470, 100), ln("111569", 470, 112),
                      ln("Ship Via ACME FREIGHT", 20, 140), ln("Collect", 300, 140),
                      ln("Shipping Number:", 300, 170), ln("0041709", 390, 170),
                      ln("Number of Packages", 300, 185), ln("2", 400, 185)])
        r = extract_from_layout(lay)
        self.assertEqual(r["trackingNumbers"], [])
        self.assertEqual([x["value"] for x in r["references"]["salesOrders"]], ["111569"])
        self.assertEqual([x["value"] for x in r["references"]["internalShippingNumbers"]], ["0041709"])
        self.assertEqual(r["carrier"], "ACME")
        self.assertIn("FREIGHT COLLECT", r["shippingDetails"]["freightTerms"])
        self.assertEqual(r["shippingDetails"]["packageCount"], 2)
        self.assertIsNone(r["shippedQuantity"])  # package count is never a product quantity


class Dates(unittest.TestCase):
    def test_ambiguous_numeric_date_is_flagged(self):
        d = parse_date("04/11/2025")
        self.assertTrue(d["ambiguous"])
        self.assertEqual(d["iso"], "2025-04-11")
        self.assertEqual(d["alternatives"], ["2025-11-04"])
        self.assertEqual(parse_date("04/11/2025", prefer="DMY")["iso"], "2025-11-04")

    def test_unambiguous_dates(self):
        self.assertFalse(parse_date("1/16/2024")["ambiguous"])
        self.assertEqual(parse_date("1/16/2024")["iso"], "2024-01-16")
        self.assertEqual(parse_date("26 Aug 2022")["iso"], "2022-08-26")
        self.assertEqual(parse_date("January 16, 2024")["iso"], "2024-01-16")
        d = parse_date("01-Oct-20")
        self.assertEqual(d["iso"], "2020-10-01")
        self.assertTrue(any("two-digit" in n for n in d["notes"]))
        self.assertIsNone(parse_date("See Pack List"))

    def test_ship_date_issue_in_draft(self):
        lay = layout([TITLE, ln("Ship Date:", 350, 60), ln("2/7/2024", 540, 60)])
        r = extract_from_layout(lay)
        self.assertEqual(r["shipDate"], "2024-02-07")
        self.assertEqual(r["rawValues"]["shipDate"], "2/7/2024")
        self.assertTrue(any(i["code"] == "ambiguous_date" for i in r["fieldIssues"]))


class LineTotalsAndDeduplication(unittest.TestCase):
    def test_repeated_page_is_counted_once_and_sublots_merge(self):
        p1 = [TITLE, *item_header(), *item_row("ABC-123", "PR", "42.000", "42.000", 315),
              ln("Lot Number: LOT:77", 60, 330), ln("42.000", 400, 330)]
        p2 = [TITLE, *item_header(), *item_row("ABC-123", "PR", "42.000", "42.000", 315),
              ln("Lot Number: A1LOT77", 60, 330), ln("20.000", 400, 330),
              ln("Lot Number: A2LOT77", 60, 342), ln("22.000", 400, 342)]
        r = extract_from_layout(layout(p1, p2))
        self.assertEqual(r["shippedQuantity"], 42.0)
        self.assertEqual(r["unitOfMeasure"], "PR")
        self.assertEqual(len(r["items"]), 1)
        self.assertEqual(r["items"][0]["pages"], [1, 2])
        self.assertEqual(sorted((s["sublotNumber"], s["quantity"]) for s in r["sublots"]),
                         [("A1", 20.0), ("A2", 22.0)])
        self.assertEqual(r["lotNumbers"], ["77"])
        self.assertTrue(any(i["code"] == "repeated_line_merged" for i in r["fieldIssues"]))
        self.assertFalse(any(i["code"] == "sublot_total_mismatch" for i in r["fieldIssues"]))

    def test_total_row_is_not_double_counted(self):
        lines = [TITLE, ln("Item: XYZ-1", 20, 250),
                 ln("Lot No", 40, 300), ln("Qty", 300, 300), ln("UOM", 360, 300),
                 ln("L100-01", 40, 315), ln("750.0000", 280, 315), ln("SF", 360, 315),
                 ln("L100-02", 40, 327), ln("750.0000", 280, 327), ln("SF", 360, 327),
                 ln("Lot: L100", 40, 345), ln("Total:", 200, 345), ln("1500.0000", 280, 345), ln("SF", 360, 345)]
        r = extract_from_layout(layout(lines))
        self.assertEqual(r["shippedQuantity"], 1500.0)
        self.assertEqual(r["unitOfMeasure"], "SF")
        self.assertEqual(r["items"][0]["itemNumber"], "XYZ-1")
        self.assertEqual(sorted(s["sublotNumber"] for s in r["sublots"]), ["L100-01", "L100-02"])
        self.assertEqual(r["lotNumbers"], ["L100"])
        self.assertFalse(any(i["code"] == "printed_total_mismatch" for i in r["fieldIssues"]))

    def test_printed_total_mismatch_is_reported(self):
        lines = [TITLE, ln("Item: XYZ-1", 20, 250),
                 ln("Lot No", 40, 300), ln("Qty", 300, 300), ln("UOM", 360, 300),
                 ln("L100-01", 40, 315), ln("750.0000", 280, 315), ln("SF", 360, 315),
                 ln("Total:", 200, 330), ln("900.0000", 280, 330), ln("SF", 360, 330)]
        r = extract_from_layout(layout(lines))
        self.assertTrue(any(i["code"] == "printed_total_mismatch" for i in r["fieldIssues"]))

    def test_same_item_in_two_sales_orders_kept_as_two_lines(self):
        lines = [TITLE, *item_header(),
                 ln("Sales Order No.: SO1, Your Reference : R1", 40, 315),
                 *item_row("NAL1", "EA", "3.00", "3.00", 330),
                 ln("Sales Order No.: SO2, Your Reference : R2", 40, 345),
                 *item_row("NAL1", "EA", "4.00", "4.00", 360)]
        r = extract_from_layout(layout(lines))
        self.assertEqual([(i["salesOrder"], i["quantityShipped"]) for i in r["items"]], [("SO1", 3.0), ("SO2", 4.0)])
        self.assertEqual(r["items"][1]["customerReference"], "R2")
        self.assertEqual(r["shippedQuantity"], 7.0)  # same item, same unit, same shipment
        self.assertTrue(any(i["code"] == "summed_lines" for i in r["fieldIssues"]))

    def test_different_items_are_not_summed(self):
        lines = [TITLE, *item_header(), *item_row("AAA-1", "EA", "2", "2", 315), *item_row("BBB-2", "EA", "5", "5", 330)]
        r = extract_from_layout(layout(lines))
        self.assertIsNone(r["shippedQuantity"])
        self.assertEqual(r["unitOfMeasure"], "EA")
        self.assertEqual(len(r["quantitySummary"]), 2)
        self.assertTrue(any(i["code"] == "multiple_items" for i in r["fieldIssues"]))

    def test_mixed_units_are_not_summed(self):
        lines = [TITLE, *item_header(), *item_row("AAA-1", "EA", "2", "2", 315), *item_row("AAA-1", "BOX", "1", "1", 330)]
        r = extract_from_layout(layout(lines))
        self.assertIsNone(r["shippedQuantity"])
        self.assertIsNone(r["unitOfMeasure"])
        self.assertTrue(any(i["code"] == "mixed_units" for i in r["fieldIssues"]))

    def test_required_shipped_outstanding_kept_distinct(self):
        lines = [TITLE, ln("Product", 40, 300), ln("Quantity", 300, 295), ln("Required", 300, 305),
                 ln("Quantity", 380, 295), ln("Shipped", 380, 305), ln("Quantity", 460, 295),
                 ln("Outstanding", 460, 305), ln("NAL9", 40, 320), ln("10.00", 300, 320), ln("6.00", 380, 320),
                 ln("4.00", 460, 320)]
        r = extract_from_layout(layout(lines))
        it = r["items"][0]
        self.assertEqual((it["quantityRequired"], it["quantityShipped"], it["quantityOutstanding"]), (10.0, 6.0, 4.0))
        self.assertEqual(r["shippedQuantity"], 6.0)

    def test_quantity_parsing_keeps_units(self):
        self.assertEqual(parse_quantity_with_unit("750.0000 SF Net Weight"), (750.0, "SF", "750.0000 SF"))
        self.assertEqual(parse_quantity_with_unit("1,500.00")[0], 1500.0)
        self.assertEqual(normalize_unit("Pair(s)"), "PR")


class MissingFields(unittest.TestCase):
    def test_missing_values_stay_null_or_empty_and_are_reported(self):
        r = extract_from_layout(layout([TITLE, ln("Thank you for your business", 40, 400)]))
        for f in ("shipDate", "carrier", "shippedQuantity", "unitOfMeasure"):
            self.assertIsNone(r[f], f)
        for f in ("trackingNumbers", "lotNumbers", "serialNumbers", "items", "sublots"):
            self.assertEqual(r[f], [], f)
        codes = {(i["field"], i["code"]) for i in r["fieldIssues"]}
        for f in ("shipDate", "carrier", "trackingNumbers", "shippedQuantity", "lotNumbers"):
            self.assertIn((f, "not_found"), codes)

    def test_identifiers_stay_strings_with_leading_zeros(self):
        lay = layout([TITLE, ln("Shipping Number:", 300, 60), ln("0041709", 390, 60),
                      ln("Tracking Number", 300, 100), ln("007751017175", 300, 112)])
        r = extract_from_layout(lay)
        self.assertEqual(r["references"]["internalShippingNumbers"][0]["value"], "0041709")
        self.assertEqual(r["trackingNumbers"], ["007751017175"])

    def test_combined_serial_lot_parenthesised_value_is_flagged_not_asserted(self):
        lines = [TITLE, ln("Qty", 60, 300), ln("Shipped", 52, 308), ln("Part Number", 100, 304),
                 ln("Serial/Lot#", 430, 304), ln("280 F-615-B130-DH", 60, 325), ln("(280)", 430, 325)]
        r = extract_from_layout(layout(lines))
        self.assertEqual(r["shippedQuantity"], 280.0)
        self.assertEqual(r["lotNumbers"], [])
        self.assertEqual(r["serialNumbers"], [])
        self.assertTrue(any(i["code"] == "ambiguous_lot_or_serial" and i["rawValue"] == "(280)"
                            for i in r["fieldIssues"]))


def ocr_layout(*pages):
    """Like layout(), but lines arrive without word boxes, as Docling's OCR delivers them."""
    built = []
    for i, specs in enumerate(pages, start=1):
        lines = [Line(t, i, x, y, x + CW * len(t), y + H) for t, x, y in specs]
        built.append(Page(i, 612, 792, lines, link_words(lines, [])))
    classify_pages(built)
    return Layout("scanned.pdf", built, len(built), text_layer=False, ocr_used=True)


class MultiItemQuantities(unittest.TestCase):
    def centred_rows_page(self):
        """Two items whose ITEM #/QUANTITY sit in the middle of tall description cells, and whose
        descriptions contain label-like text ('Form:')."""
        return [TITLE, ln("ITEM #", 33, 300), ln("QUANTITY", 80, 300), ln("DESCRIPTION", 315, 300),
                ln("Alpha-1 (A1) / Form: Powder, Grade: 99.9%", 143, 318),
                ln("Research Grade", 143, 330), ln("1", 47, 337), ln("1,000 mg", 87, 337),
                ln("HTS: 2845.90", 143, 342), ln("Certificate No.: 7562", 143, 354),
                ln("Beta-2 (B2) / Form: Pieces, Grade: 99.2%", 143, 372),
                ln("Research Grade", 143, 384), ln("2", 47, 391), ln("1,000 mg", 87, 391),
                ln("HTS: 2845.91", 143, 396), ln("Certificate No.: 89777", 143, 408)]

    def test_two_items_kept_with_their_own_descriptions(self):
        r = extract_from_layout(layout(self.centred_rows_page()))
        self.assertEqual(len(r["items"]), 2)
        a, b = r["items"]
        self.assertTrue(a["description"].startswith("Alpha-1") and "7562" in a["description"])
        self.assertTrue(b["description"].startswith("Beta-2") and "89777" in b["description"])
        self.assertNotIn("Beta", a["description"])
        self.assertEqual([(i["quantityShipped"], i["unitOfMeasure"]) for i in r["items"]], [(1000.0, "MG")] * 2)
        self.assertEqual([i["lineNumber"] for i in r["items"]], ["1", "2"])
        self.assertEqual([i["itemNumber"] for i in r["items"]], [None, None])  # 1, 2 are line numbers

    def test_multiple_items_explained_not_reported_missing(self):
        r = extract_from_layout(layout(self.centred_rows_page()))
        self.assertIsNone(r["shippedQuantity"])
        codes = {(i["field"], i["code"]) for i in r["fieldIssues"]}
        self.assertIn(("shippedQuantity", "multiple_items"), codes)
        self.assertNotIn(("shippedQuantity", "not_found"), codes)
        self.assertEqual(r["lotNumbers"], [])  # nothing invented

    def test_invoice_page_with_same_items_is_not_counted(self):
        invoice = [ln("INVOICE", 400, 40), *item_header(), *item_row("ABC-1", "EA", "5", "5", 315)]
        packing = [TITLE, *item_header(), *item_row("ABC-1", "EA", "5", "5", 315)]
        r = extract_from_layout(layout(invoice, packing))
        self.assertEqual(r["document"]["pageTypes"], {"1": "invoice", "2": "packing"})
        self.assertEqual(r["shippedQuantity"], 5.0)
        self.assertEqual(len(r["items"]), 1)


class ScannedPackageTable(unittest.TestCase):
    def scanned_page(self, box_qtys=(100, 450, 450)):
        specs = [("PACKING LIST", 240, 14), ("Ship Via:", 435, 106), ("Fed-Ex Express Saver", 487, 106),
                 # header cells printed close together: OCR gives each its own line
                 ("Line No", 16, 176), ("Catalog No", 59, 176), ("Description", 119, 176),
                 ("Qty Shipped", 363, 176), ("UOM", 422, 176),
                 ("1", 20, 190), ("8350", 58, 190), ("Shopping Tote", 118, 190), ("1000", 397, 190), ("EA", 422, 190),
                 ("Total Pack List Quantity Shipped:", 348, 226), ("1,000.00", 503, 226),
                 ("Box Number", 32, 248), ("Weight", 108, 248), ("Qty Shipped", 163, 248), ("Tracking No", 225, 248)]
        for k, q in enumerate(box_qtys):
            y = 262 + 12 * k
            specs += [(str(k + 1), 58, y), ("17", 121, y), (str(q), 184, y), (f"98308302591{k}", 226, y)]
        return specs

    def test_ocr_lines_without_word_cells_still_read_both_tables(self):
        r = extract_from_layout(ocr_layout(self.scanned_page()))
        self.assertEqual(len(r["items"]), 1)
        it = r["items"][0]
        self.assertEqual((it["itemNumber"], it["lineNumber"], it["description"]), ("8350", "1", "Shopping Tote"))
        self.assertEqual((r["shippedQuantity"], r["unitOfMeasure"]), (1000.0, "EA"))
        self.assertEqual(r["trackingNumbers"], ["983083025910", "983083025911", "983083025912"])
        self.assertEqual(r["carrier"], "FedEx")

    def test_box_quantities_are_not_added_to_the_item(self):
        r = extract_from_layout(ocr_layout(self.scanned_page()))
        self.assertEqual(r["shippedQuantity"], 1000.0)  # not 2000
        pk = r["shippingDetails"]["packages"]
        self.assertEqual([p["quantity"] for p in pk], [100.0, 450.0, 450.0])
        self.assertEqual(r["shippingDetails"]["packageCount"], 3)
        codes = {i["code"] for i in r["fieldIssues"]}
        self.assertNotIn("package_total_mismatch", codes)
        self.assertNotIn("printed_total_mismatch", codes)
        self.assertNotIn("unclassified_identifier", codes)  # box quantities never read as tracking

    def test_box_total_disagreeing_with_line_is_flagged(self):
        r = extract_from_layout(ocr_layout(self.scanned_page(box_qtys=(100, 450, 400))))
        self.assertEqual(r["shippedQuantity"], 1000.0)
        self.assertTrue(any(i["code"] == "package_total_mismatch" for i in r["fieldIssues"]))


class POComparison(unittest.TestCase):
    def draft(self, items):
        return {"items": items, "shippedQuantity": None, "unitOfMeasure": None}

    def line(self, item, qty, unit, so=None, cust=None):
        return {"itemNumber": item, "customerItemNumber": cust, "description": None, "quantityShipped": qty,
                "unitOfMeasure": unit, "salesOrder": so}

    def test_match_and_mismatch(self):
        d = self.draft([self.line("10Y1532", 42.0, "PR")])
        self.assertEqual(compare_po_quantity(d, 42, "pairs")["status"], "match")
        r = compare_po_quantity(d, 50, "PR")
        self.assertEqual((r["status"], r["difference"]), ("under_shipped", -8.0))
        self.assertEqual(compare_po_quantity(d, 40, "PR")["status"], "over_shipped")

    def test_unit_mismatch_is_not_a_quantity_mismatch(self):
        r = compare_po_quantity(self.draft([self.line("X1", 1500.0, "SF")]), 1500, "EA")
        self.assertEqual(r["status"], "cannot_compare")
        self.assertIn("Units differ", r["issues"][0])

    def test_missing_units(self):
        self.assertEqual(compare_po_quantity(self.draft([self.line("X1", 280.0, None)]), 280, "EA")["status"],
                         "cannot_compare")
        self.assertEqual(compare_po_quantity(self.draft([self.line("X1", 280.0, "EA")]), 280, None)["status"],
                         "cannot_compare")

    def test_multiple_items_need_item_number(self):
        d = self.draft([self.line("NAL1", 1.0, "EA", "SO1"), self.line("NAL2", 3.0, "EA", "SO1"),
                        self.line("NAL1", 2.0, "EA", "SO2", cust="867013-0240")])
        self.assertEqual(compare_po_quantity(d, 3, "EA")["status"], "cannot_compare")
        r = compare_po_quantity(d, 3, "EA", po_item="NAL1")
        self.assertEqual((r["status"], r["shippedQuantity"]), ("match", 3.0))
        self.assertTrue(any("several sales orders" in i for i in r["issues"]))
        r = compare_po_quantity(d, 2, "EA", po_item="867013-0240")  # customer part number also matches
        self.assertEqual(r["status"], "match")
        self.assertEqual(compare_po_quantity(d, 2, "EA", po_item="NOPE")["status"], "cannot_compare")


if __name__ == "__main__":
    unittest.main()
