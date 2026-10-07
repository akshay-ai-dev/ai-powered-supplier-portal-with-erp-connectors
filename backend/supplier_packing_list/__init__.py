"""Supplier Packing-List (SPL) integration.

Draft extraction of a supplier packing list (PDF or image) into one consistent,
reviewable response. Extraction never creates a shipment, writes an ERP document,
or submits anything — the supplier reviews and corrects the draft, then submits
through the existing shipment flow.

PDF  -> Docling-based rule extractor (``supplier_packing_list.pdf``), run in an isolated child
        process so a native Docling crash can never take down the API.
Image -> OpenAI-based extractor (``supplier_packing_list.image``), adapted from the image-to-json
        experiment, with the same validation and six-field schema.

Both paths are normalised into :class:`supplier_packing_list.schemas.DraftExtraction`.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
