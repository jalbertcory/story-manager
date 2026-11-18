"""Verify backed-up Kindle exports and pass only confirmed files to the USB cleaner."""

import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from kindle_usb import connected


def verified_book(client, story, result, path):
    # Older history rows include the upload response as text, including duplicates.
    record = re.fullmatch(r"Story Manager book (\d+)", result)
    if not record:
        record = re.fullmatch(r"Already imported\. .+ already exists \(id=(\d+)\)", result)
    asin = re.search(r"_([A-Z0-9]{10})$", path.stem)
    if not record or not asin:
        return False
    with client.open(f"{story}/api/books/{record[1]}/download", timeout=120) as response, tempfile.TemporaryFile() as epub:
        shutil.copyfileobj(response, epub)
        with zipfile.ZipFile(epub) as archive:
            root = ElementTree.fromstring(archive.read("META-INF/container.xml")).find(".//{*}rootfile")
            if root is None or archive.testzip() is not None:
                return False
            package = ElementTree.fromstring(archive.read(root.attrib["full-path"]))
            identifiers = package.findall(".//{http://purl.org/dc/elements/1.1/}identifier")
            return any(node.text == asin[1] for node in identifiers) and package.find(".//{*}spine/{*}itemref") is not None


def clean_verified(reader, stage, files, db, source, fingerprint, client, story, mode, preview, attachment):
    with tempfile.TemporaryDirectory(dir=stage) as tmp:
        approved = Path(tmp)
        shutil.copyfile(stage / ".device", approved / ".device")
        count = 0
        for path in files:
            row = db.execute(
                "SELECT result FROM imports i WHERE i.source=? AND i.digest=? AND NOT EXISTS "
                "(SELECT 1 FROM pending_series p WHERE p.source=i.source AND p.digest=i.digest)",
                (source, fingerprint(path)),
            ).fetchone()
            if not row or not verified_book(client, story, row[0], path):
                print(f"Keeping {path.name} — could not verify its Kindle ID in the saved EPUB.")
                continue
            target = approved / path.relative_to(stage)
            target.parent.mkdir(exist_ok=True)
            os.link(path, target)
            count += 1
        if not count:
            print("No verified exports to clean.")
            return
        if len(attachment) != 1 or connected() != attachment:
            raise ValueError("Kindle connection changed. Reconnect to retry cleanup.")
        action = ("preview-" if preview else "clean-") + mode
        subprocess.run([str(reader), action, str(approved), str(count)], check=True)
