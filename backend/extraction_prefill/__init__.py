"""Draft extraction of shipment/packing-list fields from a PDF or image using the OpenAI API.

The buyer's New requirement page uploads one document here; this package returns a *reviewable
draft* (ship date, carrier, tracking/lot/serial numbers, shipped quantity, line items) with
per-field evidence and warnings for missing or ambiguous values. It saves nothing: no requirement,
no attachment, no ERP call. The buyer reviews and edits the draft, then the existing requirement
creation flow persists it.

Nothing here imports Docling or any local ML model; extraction is an OpenAI API call.
"""
