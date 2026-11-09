import re

TYPES = ["patient"]

_DATE_RE = re.compile(
    r"^(?:\d{1,4}[-/]\d{1,2}[-/]\d{1,4}|\d{4})$"
)
_SSN_RE = re.compile(
    r"^(?:\d{3}|[A-Za-z]{3})-(?:\d{2}|[A-Za-z]{2})-\d{4}$"
)

def type_of(r: dict) -> str:
    def value(field):
        return str(r.get(field, "") or "").strip()

    has_name = any(value(f) for f in ("first", "middle", "last"))
    birthdate = value("birthdate")
    ssn = value("ssn")
    gender = value("gender")

    patient_signals = (
        bool(_DATE_RE.fullmatch(birthdate)),
        bool(_SSN_RE.fullmatch(ssn)),
        bool(re.fullmatch(r"[A-Za-z]", gender)),
        any(value(f) for f in ("address", "city", "zip")),
    )
    return "patient" if has_name and any(patient_signals) else "other"


CARDS = {
    "patient": """IDENTIFIES: No single field is universally decisive. A coherent normalized full name plus birthdate, corroborated by a non-placeholder full SSN, gender, or location, identifies a patient. A full SSN needs corroboration because values such as 123-45-6789 and 321-54-9876 recur; masked or alphabetic SSNs are weak.
HARMLESS: Missing middle names, initials, capitalization, hyphens, minor name typos, date-format changes, malformed dates, masked/missing SSNs, gender-code changes, and changed or missing address, city, or ZIP can occur.
VARIANT: A sustained conflict across name, birthdate, and reliable SSN indicates another person; a shared address or ZIP alone may represent household members.
SAME MEANS: Same means the same real-world human patient across participating organizations.""",

    "other": """IDENTIFIES: These are records lacking enough person-registration structure to classify as patients. No field is decisive; require a recognizable personal name together with birthdate, SSN, gender, or location evidence before linking.
HARMLESS: Blank fields, capitalization, punctuation, spacing, and formatting differences do not create a new entity.
VARIANT: Incompatible evidence about what the record describes, or incompatible person-level name, birthdate, and reliable identifier clusters, represents a different entity.
SAME MEANS: Same means the records denote the same otherwise unclassified real-world thing, supported by multiple consistent fields."""
}
