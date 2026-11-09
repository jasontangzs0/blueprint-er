import re

TYPES = ["publication", "other"]

def type_of(r: dict) -> str:
    title = str(r.get("title") or "").strip()
    authors = str(r.get("authors") or "").strip()
    journal = str(r.get("journal") or "").strip()
    year = str(r.get("year") or "").strip()
    if re.search(r"\w", title) or re.search(r"\w", authors):
        return "publication"
    if re.search(r"\w", journal) and re.fullmatch(r"\d{4}", year):
        return "publication"
    return "other"

CARDS = {
    "publication": """IDENTIFIES: A DOI embedded in the title is decisive. Otherwise a long, distinctive normalized title is decisive unless part/version/year wording conflicts; near-title matches need overlapping authors. Journal and year only corroborate.
HARMLESS: Case, punctuation, terminal periods, leading “Abstract”, manuscript/header text, section numbers, DOI/page noise, minor OCR changes; missing journal/year; journal abbreviations; initials, accents, author-order changes, duplicated authors, affiliation/member-role contamination, and occasional omitted or misspelled authors.
VARIANT: Different part, annual issue, edition, version, release, appendix, supplement, or explicit year when a title recurs; materially different titles despite shared journal, year, topic, or one author.
SAME MEANS: Both records describe the same published work, not merely related works or members of a series.""",

    "other": """IDENTIFIES: Use a stable external identifier if present; otherwise require a meaningful name or title corroborated by creator information. Bare numbers, headers, and isolated organization names are not decisive.
HARMLESS: Formatting, capitalization, punctuation, duplicated text, OCR corruption, and missing fields.
VARIANT: Different stable identifiers or clearly different named objects, creators, parts, versions, or dates.
SAME MEANS: Both records denote the same non-publication object at the dataset’s represented level."""
}
