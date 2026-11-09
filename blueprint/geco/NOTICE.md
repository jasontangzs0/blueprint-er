# Provenance / attribution — vendored GeCo corruptor

This directory contains a **vendored subset** of the GeCo data
generator/corruptor, used for the corruption step of the Synthea-based
multi-partite ER benchmark.

## Upstream

- **Original tool:** GeCo — "An online personal data Generator and Corruptor",
  Khoi-Nguyen Tran, Dinusha Vatsalan, Peter Christen, ANU (CIKM 2013).
  The corruption error models (character edit, keyboard, OCR, phonetic,
  categorical, missing) derive from Christen's record-linkage data-generation
  line (FEBRL → Christen & Pudjijono 2009 → GeCo 2013).
- **Python 3 port vendored from:** `T-Strojny/geco3`
  (https://github.com/T-Strojny/geco3), a Python-3 port of the ANU code.
- **License:** Mozilla Public License 2.0 (see `LICENSE`). MPL-2.0 is
  file-level copyleft and compatible with vendoring here with attribution.

## What we vendored

- `corruptor.py` — the corruption classes and position functions.
- `basefunctions.py` — stdlib-only helpers used by `corruptor.py`.
- `lookup/` — the calibrated lookup tables: `ocr-variations.csv`,
  `phonetic-variations.csv`, `qwerty-keyboard.csv`, `surname-misspell.csv`
  (+ `ocr-variations-upper-lower.csv`).

We did **not** vendor GeCo's generation half (`generator.py`,
`attrgenfunct.py`, demographic lookup tables) — Synthea is the generator.

## Local modifications

- `corruptor.py`: changed `import geco3.basefunctions as basefunctions` to
  `from . import basefunctions` so it imports as part of `blueprint.geco`.

No other source changes. Corruption parameters/profiles live in our own
builder code, not here.
