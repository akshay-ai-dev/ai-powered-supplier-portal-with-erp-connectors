"""PDF packing-list extraction (Docling), vendored from the
``experiments/packing_list_poc_backend`` proof of concept.

The only changes from the experiment are package-relative imports and running the
isolation worker as ``python -m supplier_packing_list.pdf.isolation`` (instead of a loose script),
so nothing relies on ``sys.path`` manipulation. The extraction rules, the
child-process isolation, timeout/retry, and the conversion-error contract are
unchanged.

Public entry points used by the integration::

    from supplier_packing_list.pdf.isolation import convert_isolated, is_conversion_error
"""
