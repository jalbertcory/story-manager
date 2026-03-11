"""Series detection: infers series groupings from book title patterns."""

import re


def detect_series_from_titles(titles: list[str]) -> dict[str, str]:
    """
    Given a list of book titles, detect which ones belong to a series.

    Pass 1 — numbered anchors: looks for "<series> <number|roman> [- <subtitle>]".
    A series prefix is confirmed only when 2+ numbered entries share it.

    Pass 2 — unnumbered members: for each confirmed prefix, also matches:
      - a title that IS exactly the prefix  (e.g. "12 Miles Below")
      - a title that starts with the prefix + ": " or " - "
        (e.g. "12 Miles Below: A Prog Fantasy")
    """
    _ROMAN = re.compile(
        r"^M{0,4}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})$",
        re.IGNORECASE,
    )
    _TITLE_RE = re.compile(r"^(.+?)\s+(\d+|[IVXLCDMivxlcdm]+)(?:\s*[-:]\s*.+)?$")

    # Pass 1: collect (normalized_key, original_prefix) for numbered titles
    parsed: dict[str, tuple[str, str]] = {}
    for title in titles:
        m = _TITLE_RE.match(title.strip())
        if not m:
            continue
        prefix, num = m.group(1).strip(), m.group(2)
        if not num.isdigit() and not _ROMAN.match(num):
            continue
        parsed[title] = (prefix.lower(), prefix)

    groups: dict[str, dict] = {}
    for title, (key, prefix) in parsed.items():
        if key not in groups:
            groups[key] = {"prefix": prefix, "titles": []}
        groups[key]["titles"].append(title)

    result: dict[str, str] = {}
    confirmed: dict[str, str] = {}  # normalized_key -> canonical prefix
    for key, group in groups.items():
        if len(group["titles"]) >= 2:
            for title in group["titles"]:
                result[title] = group["prefix"]
            confirmed[key] = group["prefix"]

    # Pass 2: pull in unnumbered titles that match a confirmed prefix
    for title in titles:
        if title in result:
            continue
        t = title.strip().lower()
        for key, prefix in confirmed.items():
            if t == key or t.startswith(key + ": ") or t.startswith(key + " - "):
                result[title] = prefix
                break

    return result
