TYPES = ["song", "other"]


def type_of(r: dict) -> str:
    if not isinstance(r, dict):
        return "other"
    title = str(r.get("title") or "").strip()
    artist = str(r.get("artist_name") or "").strip()
    release = str(r.get("release") or "").strip()
    return "song" if title or (artist and release) else "other"


CARDS = {
    "song": """IDENTIFIES: No field is decisive alone. The strongest identity is normalized artist_name plus the full title, including meaningful mix/performance qualifiers. Minor artist-credit differences need corroboration from title and, when reliable, similar duration. HARMLESS: Different release, compilation, release year, missing or implausible year, capitalization, punctuation, accents, apostrophes, spacing, and remaster/album/LP retailer wording. Duration may differ slightly or even substantially in this data, so it cannot reject an otherwise exact artist-title match. VARIANT: Different song title, performer, featured artist affecting the credited performance, remix, live take, demo, instrumental, radio/edit/short/extended mix, alternate version, cover, medley contents, or other performance/version qualifier. SAME MEANS: The records denote the same credited song rendition despite appearing on different releases or carrying noisy metadata.""",

    "other": """IDENTIFIES: A record lacking a usable title and lacking the artist_name-plus-release pattern is unclassifiable; no supplied field then identifies a song. HARMLESS: Missing year or duration, empty optional values, formatting, capitalization, punctuation, and implausible numeric metadata do not by themselves make a populated song record “other.” VARIANT: Any evidence that the record represents a non-song object, or a separately titled or separately performed track, makes it a different entity rather than the same unknown item. SAME MEANS: Two “other” records are the same only when independent populated metadata clearly shows they denote the same otherwise-unclassified object."""
}
