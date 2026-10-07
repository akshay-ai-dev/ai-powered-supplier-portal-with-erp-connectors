"""Image packing-list extraction (OpenAI), vendored from
``experiments/image-to-json-backend/app``.

Changes from the experiment: package-relative imports and a ``config`` that reads
the API key and model from the process environment only (never a committed file).
The image validation (:mod:`supplier_packing_list.image.image_processing`), the OpenAI Structured
Outputs call (:mod:`supplier_packing_list.image.extraction`), and the six-key schema
(:mod:`supplier_packing_list.image.schemas`) are otherwise unchanged.

The web app layer (the experiment's ``app/api.py`` and ``app/batch.py``) is
deliberately NOT vendored — the integration provides its own authenticated route
and never writes result files to disk.
"""
