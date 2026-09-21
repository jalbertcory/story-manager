"""Catalog search treats user input as literal text in both books and groups."""

import pytest

from backend.app import models
from backend.app.services.catalog import build_book_catalog_page
from backend.app.services.library import library_groups


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["%", "_", "\\", "/", "%_\\/"])
@pytest.mark.parametrize("field", ["title", "author", "series", "genre_tags", "universe"])
async def test_search_metacharacters_match_literal_text(db, query, field):
    matching = models.Book(title="Matching", author="Writer", series="Saga", source_type=models.SourceType.epub)
    other = models.Book(title="Other", author="Writer", series="Other", source_type=models.SourceType.epub)
    text = f"Before{query}After"
    if field == "universe":
        universe = models.Universe(name=text, name_key=text.casefold())
        db.add(universe)
        await db.flush()
        db.add(models.UniverseSeries(universe_id=universe.id, series_key="saga"))
    else:
        setattr(matching, field, [text] if field == "genre_tags" else text)
    db.add_all([matching, other])
    await db.commit()

    page = await build_book_catalog_page(db, view="all", q=query)
    assert [book.id for book in page.items] == [matching.id]
    groups = await library_groups(db, group_by="series", q=query, universe=None, source=None)
    assert sum(group["book_count"] for group in groups) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("tag,other_tag", [("100%", "100 percent"), ("sci_fi", "sci-fi"), ("a/b", "a/bc"), ("a\\b", "ab")])
async def test_genre_filter_matches_literal_exact_tag(db, tag, other_tag):
    matching = models.Book(title="Matching", author="Writer", source_type=models.SourceType.epub, genre_tags=[tag])
    db.add_all(
        [
            matching,
            models.Book(title="Other", author="Writer", source_type=models.SourceType.epub, genre_tags=[other_tag]),
        ]
    )
    await db.commit()
    page = await build_book_catalog_page(db, view="all", genre=f" {tag.upper()} ")
    assert [book.id for book in page.items] == [matching.id]


@pytest.mark.asyncio
async def test_search_keeps_case_insensitive_substring_matching(db):
    db.add(models.Book(title="The Quiet Forest", author="Writer", source_type=models.SourceType.epub))
    await db.commit()
    assert (await build_book_catalog_page(db, view="all", q=" QUIET ")).total_count == 1
