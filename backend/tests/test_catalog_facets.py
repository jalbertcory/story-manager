"""Genre facets count matching books once per normalized tag."""

from datetime import datetime, timezone

import pytest

from backend.app import models
from backend.app.services.catalog import build_book_catalog_page
from backend.app.services.library import library_groups


@pytest.mark.asyncio
async def test_genre_counts_deduplicate_case_variants_across_tag_sources(db):
    db.add_all(
        [
            models.Book(
                title="First",
                author="Writer",
                series="Saga",
                source_type=models.SourceType.epub,
                genre_tags=["Fantasy", "fantasy", "Mystery"],
                user_genre_tags=["FANTASY", "Mystery"],
            ),
            models.Book(
                title="Second",
                author="Writer",
                series="Saga",
                source_type=models.SourceType.epub,
                genre_tags=["Fantasy"],
                user_genre_tags=["fantasy"],
            ),
            models.Book(title="Untagged", author="Writer", source_type=models.SourceType.epub),
            models.Book(
                title="Deleted",
                author="Writer",
                source_type=models.SourceType.epub,
                genre_tags=["Fantasy"],
                deleted_at=datetime.now(timezone.utc),
            ),
        ]
    )
    await db.commit()

    page = await build_book_catalog_page(db, view="all")
    counts = {genre.name.casefold(): genre.count for genre in page.facets.genres}
    assert counts == {"fantasy": 2, "mystery": 1}
    for genre in page.facets.genres:
        filtered = await build_book_catalog_page(db, view="all", genre=genre.name)
        assert filtered.total_count == genre.count

    groups = await library_groups(db, group_by="series", q="", universe=None, source=None, limit=10)
    assert {genre["name"].casefold(): genre["count"] for genre in groups["facets"]["genres"]} == counts

    searched = await build_book_catalog_page(db, view="all", q="First")
    assert {genre.name.casefold(): genre.count for genre in searched.facets.genres} == {"fantasy": 1, "mystery": 1}
