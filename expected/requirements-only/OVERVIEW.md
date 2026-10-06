# Expected results: original five PDFs (draft for supplier review)

| PDF | Ship date | Carrier | Tracking | Shipped qty + unit | Lot / serial | Needs review |
|---|---|---|---|---|---|---|
| pdf-1 | 2020-10-01 | FedEx | none | 1500 SF | Lot 6446 / none | Tracking: "FED EX# 149752137" unclear |
| pdf-2 | 2024-02-07 | FedEx | 4 numbers | 280, no unit | none / none | Date order, unit, "(280)" lot/serial |
| pdf-3 | none | DPL/LOGIFISH | none | 150, no unit | Lot 9399 / none | Ship date, unit |
| pdf-4 | 2022-08-26 | none (collection) | none | null (5 products) | 5 batches / none | Multiple items, unit, carrier |
| pdf-5 | 2024-01-16 | UPS | none | 42 PR | Lot 2401 / none | Nothing beyond missing tracking |

No PO quantity was supplied, so `poQuantity` and `quantityMismatch` are null for every PDF.
