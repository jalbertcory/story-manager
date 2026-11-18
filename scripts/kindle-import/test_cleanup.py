import io
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from cleanup import clean_verified, verified_book


def epub(asin):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as z:
        z.writestr("META-INF/container.xml", '<container><rootfile full-path="book.opf"/></container>')
        z.writestr(
            "book.opf",
            f'<package xmlns:dc="http://purl.org/dc/elements/1.1/"><metadata>'
            f"<dc:identifier>{asin}</dc:identifier></metadata><spine><itemref/></spine></package>",
        )
    data.seek(0)
    return data


class CleanupTests(unittest.TestCase):
    def test_duplicate_requires_matching_epub_identifier(self):
        path = Path("Sample_B000000001.kfx-zip")
        result = "Already imported. A book with title 'Sample' already exists (id=6)"
        client = Mock()
        client.open.side_effect = [epub("B000000002"), epub("B000000001")]
        self.assertFalse(verified_book(client, "http://story", result, path))
        self.assertTrue(verified_book(client, "http://story", result, path))
        self.assertFalse(verified_book(client, "http://story", result, Path("Unknown.epub")))

    def test_only_completed_and_verified_exports_are_passed_to_reader(self):
        with tempfile.TemporaryDirectory() as tmp, sqlite3.connect(":memory:") as db:
            stage = Path(tmp)
            (stage / ".device").write_text("usb")
            sources = []
            for i in range(4):
                p = stage / str(i) / f"Book_B00000000{i}.kfx-zip"
                p.parent.mkdir()
                p.write_text(str(i))
                sources.append(p)
            db.execute("CREATE TABLE imports(source,digest,result)")
            db.execute("CREATE TABLE pending_series(source,digest)")
            db.executemany(
                "INSERT INTO imports VALUES ('library',?,?)", [(str(i), f"Story Manager book {i}") for i in range(3)]
            )
            db.execute("INSERT INTO pending_series VALUES ('library','2')")
            client = Mock()
            client.open.side_effect = [epub("B000000000"), epub("B000000009")]

            def inspect(command, check):
                _, mode, folder, count = command
                self.assertEqual((mode, count, check), ("preview-books", "1", True))
                self.assertEqual([p.read_text() for p in Path(folder).glob("*/*.kfx-zip")], ["0"])

            with patch("cleanup.connected", return_value={42}), patch("cleanup.subprocess.run", side_effect=inspect) as run:
                clean_verified(
                    "reader", stage, sources, db, "library", Path.read_text, client, "http://s", "books", True, {42}
                )
                run.assert_called_once()
