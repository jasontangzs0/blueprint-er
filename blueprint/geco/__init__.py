"""Vendored GeCo corruption functions (MPL-2.0). See NOTICE.md for provenance.

We use only the *corruption* half of GeCo: the calibrated character-edit,
keyboard, OCR, phonetic, categorical and missing-value corruptors, plus the
lookup tables that back them. Generation is handled by Synthea, not GeCo.

``LOOKUP_DIR`` resolves the bundled lookup CSVs regardless of working
directory, so callers can do::

    import os
    from blueprint import geco
    ocr = geco.corruptor.CorruptValueOCR(
        position_function=geco.corruptor.position_mod_normal,
        lookup_file_name=os.path.join(geco.LOOKUP_DIR, "ocr-variations.csv"),
    )
"""

import os

from . import basefunctions, corruptor

LOOKUP_DIR = os.path.join(os.path.dirname(__file__), "lookup")

__all__ = ["basefunctions", "corruptor", "LOOKUP_DIR"]
