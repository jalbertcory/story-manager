import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
import re


def get_chapters(epub_path: str):
    book = epub.read_epub(epub_path)
    chapters = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        chapters.append(
            {
                "filename": item.get_name(),
                "title": item.get_name(),
                "content": item.get_content().decode("utf-8", "ignore"),
            }
        )
    return chapters


def get_word_count(epub_path: str) -> int:
    book = epub.read_epub(epub_path)
    word_count = 0
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        content = item.get_content()
        soup = BeautifulSoup(content, "html.parser")
        text = soup.get_text()
        word_count += len(re.findall(r"\S+", text))
    return word_count


def process_epub(
    immutable_path: str,
    current_path: str,
    removed_chapters: list[str],
    div_selectors: list[str],
):
    book = epub.read_epub(immutable_path)
    new_book = epub.EpubBook()

    # Copy metadata
    for key, value in book.metadata.items():
        new_book.metadata[key] = value

    items_to_keep = []
    for item in book.items:
        if item.get_name() not in removed_chapters:
            if item.get_type() == ebooklib.ITEM_DOCUMENT:
                content = item.get_content().decode("utf-8", "ignore")
                soup = BeautifulSoup(content, "html.parser")
                for selector in div_selectors:
                    for div in soup.select(selector):
                        div.decompose()
                item.set_content(str(soup).encode("utf-8"))
            items_to_keep.append(item)
            new_book.add_item(item)

    # Rebuild spine
    new_book.spine = [item for item in book.spine if book.get_item_with_id(item[0]).get_name() not in removed_chapters]
    new_book.toc = [
        link for link in book.toc if isinstance(link, epub.Link) and link.href.split("#")[0] not in removed_chapters
    ]

    epub.write_epub(current_path, new_book, {})
