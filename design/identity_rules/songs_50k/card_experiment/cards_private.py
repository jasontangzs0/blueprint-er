import re

TYPES = [
    "standard_song",
    "versioned_song",
    "medley",
    "classical_movement",
    "masked_record",
    "other",
]

_VERSION_RE = re.compile(
    r"\b(?:"
    r"remix\w*|mix|extended|radio\s+(?:mix|edit)|edit(?:ed)?|"
    r"live(?:\s+recording)?|demo|instrumental|alternate|acoustic|"
    r"album\s+version|lp\s+version|track\s+edition|"
    r"remaster(?:ed)?|digitally\s+remastered|digital\s+remaster|"
    r"session|stereo|mono|quick\s+trim|restored"
    r")\b",
    re.IGNORECASE,
)

_CLASSICAL_RE = re.compile(
    r"(?:"
    r"\b(?:sonata|sonatas|symphony|concerto|prelude|ensemble)s?\b"
    r".{0,45}\b(?:no\.?\s*\d+|op\.?\s*\d+|in\s+[a-g](?:\s+(?:sharp|flat|major|minor))?)"
    r"|"
    r"\b(?:no\.?\s*\d+|op\.?\s*\d+)\b.{0,45}"
    r"\b(?:presto|allegro|adagio|andante|scherzo|largo|major|minor)\b"
    r")",
    re.IGNORECASE,
)

_MEDLEY_RE = re.compile(r"\bmedley\b", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[A-Za-z]+")


def _is_masked_text(text):
    tokens = _TOKEN_RE.findall(text or "")
    if not tokens:
        return False
    runs = [
        token for token in tokens
        if len(token) >= 4 and len(set(token.lower())) == 1
    ]
    x_placeholders = [
        token for token in tokens
        if len(token) >= 5 and re.fullmatch(r"[A-Za-z]?[xX]{4,}", token)
    ]
    return len(runs) >= 2 or len(x_placeholders) >= 2


def type_of(r: dict) -> str:
    title = str(r.get("title") or "").strip()
    release = str(r.get("release") or "").strip()
    artist = str(r.get("artist_name") or "").strip()
    combined = " ".join((title, release, artist))

    if _is_masked_text(combined):
        return "masked_record"

    if _CLASSICAL_RE.search(title):
        return "classical_movement"

    if _MEDLEY_RE.search(title) or len(re.findall(r"\s+/\s+", title)) >= 1:
        return "medley"

    if _VERSION_RE.search(title):
        return "versioned_song"

    if title and artist:
        return "standard_song"

    return "other"


CARDS = {
    "standard_song": """IDENTIFIES: Normalized title plus normalized artist_name identifies the song; neither is normally decisive alone. Duration agreement, allowing small rounding differences, strongly corroborates the pair and is required for generic titles such as “Song”, “Glint”, or “Nimbus”. Release and year are weak evidence only.
HARMLESS: Case, accents, punctuation, apostrophes, spacing, conjunction style, reordered featured-artist wording, rounded duration, missing year, and a different release.
VARIANT: A different primary performer, materially different duration, remix, live take, demo, edit, instrumental, alternate version, or other explicit recording/version label indicates a different dataset song.
SAME MEANS: The records denote the same artist’s same unqualified song recording, even when issued on different releases.""",

    "versioned_song": """IDENTIFIES: Base title, primary artist, and the complete version qualifier jointly identify the entity. Named remixers, live venue/date, session, demo, edit, instrumental, remaster, stereo/mono, album/LP, or radio labels are identity-bearing; duration is strong corroboration. Release is not decisive.
HARMLESS: Case, punctuation, bracket type, duplicated qualifier text, minor wording such as “digitally remastered” versus “digital remaster”, duration rounding, missing year, and appearance on another release.
VARIANT: A different remix name, performance date or place, edit, take, demo, mix, instrumentation, channel format, or materially different duration is a different entity.
SAME MEANS: The records denote the same specifically labelled version of the same song by the same primary artist.""",

    "medley": """IDENTIFIES: The ordered component-title sequence plus artist_name identifies a medley; duration corroborates and helps distinguish similarly titled programmes. An explicit “Medley” label or spaced slash-separated titles signals this kind. Release and year are not decisive.
HARMLESS: “Medley:” wording, slash versus semicolon separators, punctuation, case, translated conjunctions, abbreviated component names when the sequence remains clear, rounded duration, and different releases.
VARIANT: Adding, removing, substituting, or reordering a component; changing the performer; using a different live or studio rendition; or materially changing the medley version creates a different entity.
SAME MEANS: The records denote the same ordered combination of songs performed as one track by the same artist.""",

    "classical_movement": """IDENTIFIES: Structured work title, number, key, opus/catalogue number, movement designation, and artist_name jointly identify the track. Opus/catalogue plus movement is highly distinctive but still needs performer or duration because this dataset distinguishes recordings. Duration corroborates; release and year do not decide identity.
HARMLESS: Roman versus Arabic numerals, “No.” formatting, punctuation, translated tempo terms, key-name spelling, reordered work metadata, rounded duration, and different releases.
VARIANT: A different work, opus, number, key, movement, performer/ensemble, movement selection, arrangement, or recorded performance is different.
SAME MEANS: The records denote the same performer’s recording of the same classical work or movement.""",

    "masked_record": """IDENTIFIES: Placeholder-heavy titles such as “Xxxxx” cannot identify an entity alone. Require agreement across the residual title pattern, artist pattern, release context, and near-exact duration; no masked textual field is decisive by itself. A plausible unmasked counterpart needs exceptionally strong duration and contextual agreement.
HARMLESS: Different capitalization or lengths of placeholder runs, punctuation, spacing, missing year, duration rounding, and masking of additional words.
VARIANT: Conflicting visible words, incompatible artist or release patterns, materially different duration, or a distinct visible version qualifier indicates a different entity.
SAME MEANS: The records are the same only when the masked structures and remaining high-information evidence support one specific song.""",

    "other": """IDENTIFIES: Use the strongest available combination of title, artist_name, and duration. A distinctive title-artist pair with closely matching duration may identify the song; release and year only corroborate because releases vary and sampled years are often missing or implausible.
HARMLESS: Case, accents, punctuation, whitespace, minor credit formatting, rounded duration, missing values, and different release names.
VARIANT: Conflicting primary artist, materially different title, duration inconsistent with formatting tolerance, or a different explicit mix, live take, demo, edit, movement, or medley composition indicates a different entity.
SAME MEANS: The records denote the same dataset-level song recording despite incomplete or irregular metadata.""",
}
