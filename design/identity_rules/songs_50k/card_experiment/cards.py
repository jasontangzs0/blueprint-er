import re

TYPES = ["song", "medley", "classical", "spoken_word", "other"]

_CLASSICAL_RE = re.compile(
    r"\b(?:concerto|concerti|symphony|sonata|sonatina|string quartet|"
    r"nocturnes?|scherzo|presto|adagio|andante|rondo|raga|overture|"
    r"opera|choral|hymns?|opus|op\.?\s*\d|major|minor|bach|chopin|"
    r"handel|mendelssohn|mussorgsky|schubert|liszt|debussy)\b",
    re.IGNORECASE,
)
_MEDLEY_RE = re.compile(
    r"^\s*medley\b|\s[/;]\s|(?:\b(?:and|&)\b.*){2,}",
    re.IGNORECASE,
)
_SPOKEN_RE = re.compile(
    r"\b(?:spoken word|speech|poetry|poem|narration|audiobook|"
    r"musical biography|chief executives)\b",
    re.IGNORECASE,
)
_SPOKEN_ARTIST_RE = re.compile(
    r"^(?:langston hughes|walter brennan)$",
    re.IGNORECASE,
)


def type_of(r: dict) -> str:
    title = str(r.get("title") or "").strip()
    release = str(r.get("release") or "").strip()
    artist = str(r.get("artist_name") or "").strip()

    if not title or not artist:
        return "other"

    combined = f"{title} {release}"
    if _CLASSICAL_RE.search(combined):
        return "classical"
    if _SPOKEN_RE.search(combined) or _SPOKEN_ARTIST_RE.search(artist):
        return "spoken_word"
    if _MEDLEY_RE.search(title):
        return "medley"
    return "song"


CARDS = {
    "song": """IDENTIFIES: Canonical title plus credited artist identifies a song; close duration strongly corroborates it. An exact artist-title pair is usually decisive only when version labels also agree. Release and year are supporting evidence, not identifiers alone.
HARMLESS: Different releases, compilations, capitalization, punctuation, accents, “LP Version,” “Album Version,” remaster wording, mono/stereo wording, retailer text, missing year, and small duration differences from encoding or silence.
VARIANT: Live performances, radio sessions, demos, alternate takes, named remixes, acoustic or instrumental recordings, clean/edited versions, shortened edits, and materially different featured-artist credits are different entities.
SAME MEANS: The records represent the same artist recording in the same substantive version, regardless of release.""",

    "medley": """IDENTIFIES: The ordered component-title sequence plus credited artist identifies the medley; duration and live/session wording corroborate it. “Medley” alone, one shared component, or the release title is not decisive.
HARMLESS: Slash versus semicolon separators, punctuation, capitalization, translated conjunctions, abbreviated component titles, release changes, remaster labels, missing year, and small duration drift.
VARIANT: Adding, removing, reordering, or substantially shortening components; a different performer; a different live performance; a named remix; or a different take creates another entity.
SAME MEANS: The records contain the same artist’s same ordered combination and performance/version of the component songs.""",

    "classical": """IDENTIFIES: Work name or catalogue/opus number, movement number or tempo, credited performer/conductor/ensemble, and duration identify the entity together. Catalogue plus movement identifies the composition but not necessarily this dataset’s recording; performer and duration provide required corroboration.
HARMLESS: Translated work names, Roman versus Arabic numerals, key-name formatting, composer-name order, punctuation, abbreviated instrumentation, different releases, remaster wording, missing year, and slight duration differences.
VARIANT: A different movement, arrangement, performer or conductor, live performance, take, edit, instrumentation, or materially different duration is a different entity.
SAME MEANS: The records represent the same performed recording of the same classical work or movement.""",

    "spoken_word": """IDENTIFIES: Spoken-piece title plus speaker or credited artist identifies the item, with program/release context and duration as corroboration. Generic titles are not decisive without matching speaker and duration.
HARMLESS: Release or compilation changes, subtitle punctuation, capitalization, remaster wording, chapter-number formatting, missing year, and small duration differences caused by mastering.
VARIANT: A different speaker, reading, speech occasion, chapter, script, language performance, edit, excerpt boundary, or live recording is a different entity.
SAME MEANS: The records contain the same spoken performance or recording of the same text or program segment.""",

    "other": """IDENTIFIES: Use matching nonempty title and credited artist, supported by duration, year, and release context. No single generic or missing field is decisive.
HARMLESS: Formatting, capitalization, punctuation, release changes, missing year, remaster wording, and minor duration variation.
VARIANT: Different credited creator, substantive title, content, performance, remix, edit, take, or component structure indicates a different entity.
SAME MEANS: The records denote the same identifiable audio item at the dataset’s recording-level granularity."""
}
