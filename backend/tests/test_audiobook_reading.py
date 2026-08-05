from zipfile import ZipFile

from backend.app.services.audiobook_reading import reading_blocks_from_epub


def test_reading_blocks_preserve_epub_paragraphs_and_semantics(tmp_path):
    epub_path = tmp_path / "book.epub"
    with ZipFile(epub_path, "w") as archive:
        archive.writestr(
            "EPUB/text/chapter.xhtml",
            """
            <html><body>
              <h1><span id="heading">One</span></h1>
              <p><span id="first">First sentence.</span>
                 <i><span id="second">Second sentence.</span></i></p>
              <blockquote><p><span id="quote">Quoted sentence.</span></p></blockquote>
              <ul><li><p><span id="item">Listed sentence.</span></p></li></ul>
            </body></html>
            """,
        )

    blocks = reading_blocks_from_epub(epub_path, "text/chapter.xhtml")

    assert blocks["heading"].kind == "heading"
    assert blocks["first"].kind == "paragraph"
    assert blocks["first"].index == blocks["second"].index
    assert blocks["quote"].kind == "quote"
    assert blocks["item"].kind == "list-item"
    assert len({block.index for block in blocks.values()}) == 4


def test_reading_blocks_gracefully_handle_missing_chapter(tmp_path):
    epub_path = tmp_path / "book.epub"
    with ZipFile(epub_path, "w") as archive:
        archive.writestr("EPUB/text/other.xhtml", "<html><body>Other</body></html>")

    assert reading_blocks_from_epub(epub_path, "text/missing.xhtml") == {}
