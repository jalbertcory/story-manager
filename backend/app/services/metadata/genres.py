"""Genre tag derivation and merging for metadata sync."""

from collections.abc import Iterable

from .scoring import normalize_text

_GENRE_KEYWORDS = (
    ("progression fantasy", "Progression Fantasy"),
    ("urban fantasy", "Urban Fantasy"),
    ("epic fantasy", "Epic Fantasy"),
    ("science fiction", "Science Fiction"),
    ("sci-fi", "Science Fiction"),
    ("historical fiction", "Historical Fiction"),
    ("young adult", "Young Adult"),
    ("short stories", "Short Stories"),
    ("detective", "Detective"),
    ("thriller", "Thriller"),
    ("mystery", "Mystery"),
    ("fantasy", "Fantasy"),
    ("romance", "Romance"),
    ("horror", "Horror"),
    ("adventure", "Adventure"),
    ("dystopian", "Dystopian"),
    ("dystopia", "Dystopian"),
    ("paranormal", "Paranormal"),
    ("supernatural", "Supernatural"),
    ("crime", "Crime"),
    ("literary", "Literary Fiction"),
    ("humor", "Humor"),
    ("satire", "Satire"),
    ("steampunk", "Steampunk"),
    ("cyberpunk", "Cyberpunk"),
    ("litrpg", "LitRPG"),
    ("mythology", "Mythology"),
    ("war stories", "War"),
    ("xianxia", "Xianxia"),
    ("cultivation", "Cultivation"),
)


def derive_genre_tags(subjects: Iterable[str]) -> list[str]:
    genres: list[str] = []
    seen: set[str] = set()

    for subject in subjects:
        normalized = normalize_text(subject)
        for keyword, canonical in _GENRE_KEYWORDS:
            if keyword in normalized and canonical.casefold() not in seen:
                seen.add(canonical.casefold())
                genres.append(canonical)

    return genres


def merge_genre_tags(*groups: Iterable[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for tag in group:
            folded = tag.casefold()
            if folded in seen:
                continue
            seen.add(folded)
            merged.append(tag)
    return merged
