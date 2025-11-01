import zipfile
from bs4 import BeautifulSoup
import ebooklib
from ebooklib import epub

def get_epub_chapters(epub_path: str):
    book = epub.read_epub(epub_path)
    chapters = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        chapters.append({'filename': item.get_name(), 'title': item.get_name()})
    return chapters

def remove_epub_chapter(epub_path: str, filename: str):
    with zipfile.ZipFile(epub_path, 'a') as zf:
        # This is a placeholder. zipfile does not support deleting files.
        # A new zip file will need to be created without the specified file.
        pass

def clean_epub_divs(epub_path: str, selectors: list):
    # This is a placeholder.
    pass
