#!/usr/bin/env python3
"""Import Kindle exports through Calibre and Story Manager."""

import argparse
import fcntl
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import (
    build_opener,
    HTTPDigestAuthHandler,
    HTTPPasswordMgrWithDefaultRealm,
    HTTPRedirectHandler,
    ProxyHandler,
    Request,
)
import uuid
import zipfile
from xml.etree.ElementTree import ParseError

from cleanup import clean_verified
from kindle_usb import connected

CONFIG = Path(__file__).with_name("config.local.json")
STATE = Path.home() / "Library/Application Support/Kindle Story Import"
FORMATS = {".kfx-zip", ".kfx", ".azw3", ".mobi", ".epub"}


class DirectOnly(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def opener(base, user, password=None):
    handlers = [ProxyHandler({}), DirectOnly()]
    if user:
        credentials = HTTPPasswordMgrWithDefaultRealm()
        if password is None:
            if not sys.stdin.isatty():
                raise ValueError("Set calibre_password in config.local.json for unattended login.")
            password = getpass.getpass("Calibre password: ")
        credentials.add_password(None, base + "/", user, password)
        handlers.append(HTTPDigestAuthHandler(credentials))
    return build_opener(*handlers)


def api(client, url, data=None, content_type="application/json", method=None):
    headers = {"Accept": "application/json", "Content-Type": content_type}
    with client.open(Request(url, data=data, headers=headers, method=method), timeout=120) as response:
        return json.load(response)


def find_sources(folder):
    files = []
    if not folder.is_dir():
        raise ValueError(f"Cannot open {folder}")
    for path in sorted(folder.rglob("*")):
        if any(part.startswith(".") for part in path.relative_to(folder).parts):
            continue
        if path.is_file() and not path.is_symlink() and path.suffix.lower() in FORMATS:
            files.append(path)
    return files


def build_reader(helper):
    prefixes = (Path("/opt/homebrew/opt/libmtp"), Path("/usr/local/opt/libmtp"))
    prefix = next((p for p in prefixes if (p / "include/libmtp.h").is_file()), None)
    if not prefix:
        raise ValueError("No Kindle drive found. Reading a Kindle over MTP requires Homebrew libmtp.")
    env = os.environ.copy()
    xcode = Path("/Applications/Xcode.app/Contents/Developer")
    if xcode.is_dir():
        env.setdefault("DEVELOPER_DIR", str(xcode))
    subprocess.run(
        [
            "xcrun",
            "--sdk",
            "macosx",
            "clang",
            str(Path(__file__).with_name("kindle_mtp.c")),
            "-I" + str(prefix / "include"),
            "-L" + str(prefix / "lib"),
            "-lmtp",
            "-o",
            str(helper),
        ],
        env=env,
        check=True,
    )


def usb_reader(stage):
    helper = Path(__file__).with_name("kindle-reader")
    if not helper.is_file():
        helper = stage / "kindle-reader"
        build_reader(helper)
    return helper


def usb_sources(stage, check):
    helper = usb_reader(stage)
    result = subprocess.run([str(helper), "list" if check else "read", str(stage)])
    if result.returncode == 2:
        if check:
            print("No Kindle connected.")
            return []
        raise ValueError("Connect the Kindle by USB, or specify a local export folder.")
    result.check_returncode()
    return find_sources(stage)


def fingerprint(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def add_book(client, base, library, path):
    route = f"/cdb/add-book/{uuid.uuid4().hex}/n/{quote(path.name, safe='')}/{library}"
    # Keep the input rewindable for a Digest authentication challenge.
    result = api(client, base + route, path.read_bytes(), "application/octet-stream")
    if result.get("book_id"):
        return int(result["book_id"])
    if not result.get("duplicates"):
        raise ValueError("Calibre did not return a book ID or a duplicate match.")
    # Calibre's duplicate response names the book but supplies no ID. Resolve
    # only an exact title and author list, so similar editions remain separate.
    title = result["title"]
    escaped = title.replace("\\", "\\\\").replace('"', '\\"')
    query = urlencode({"query": f'title:"={escaped}"', "num": 100})
    found = api(client, f"{base}/ajax/search/{library}?{query}")
    ids = found["book_ids"]
    if not ids or len(ids) != found["total_num"]:
        raise ValueError(f"Could not uniquely identify the existing Calibre book {title!r}.")
    query = urlencode({"ids": ",".join(map(str, ids)), "category_urls": "false"})
    books = api(client, f"{base}/ajax/books/{library}?{query}")
    matches = [int(i) for i, b in books.items() if b and b["title"] == title and b["authors"] == result["authors"]]
    if len(matches) != 1:
        raise ValueError(f"Calibre has no unique exact match for {title!r}. Review its editions.")
    return matches[0]


def ensure_epub(client, base, library, book_id):
    metadata = api(client, f"{base}/ajax/book/{book_id}/{library}?category_urls=false")
    if "epub" in {fmt.lower() for fmt in metadata["formats"]}:
        return metadata
    query = f"library_id={library}&output_fmt=epub"
    options = api(client, f"{base}/conversion/book-data/{book_id}?{query}")
    inputs = [fmt for fmt in options["input_formats"] if "." + fmt.lower() in FORMATS]
    if not inputs:
        raise ValueError(f"No supported Kindle conversion for Calibre book {book_id}.")
    body = json.dumps({"input_fmt": inputs[0], "output_fmt": "epub", "options": {}}).encode()
    job = api(client, f"{base}/conversion/start/{book_id}?{query}", body)
    if type(job) is not int:
        raise ValueError("Calibre did not return a conversion job number.")
    print(f"  Converting {metadata['title']} to EPUB …", flush=True)
    while True:
        # Polling the completed job also saves its EPUB into the Calibre library.
        status = api(client, f"{base}/conversion/status/{job}?{query}", b"{}")
        if not status["running"]:
            if not status.get("ok"):
                log = status.get("log") or status.get("traceback") or "See the Calibre job log."
                raise ValueError(f"Calibre conversion failed. {log[-600:]}")
            return metadata
        time.sleep(2)


def send_epub(client, base, library, book_id, story):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "book.epub"
        with client.open(f"{base}/get/EPUB/{book_id}/{library}", timeout=120) as response:
            with path.open("wb") as output:
                shutil.copyfileobj(response, output)
        with zipfile.ZipFile(path) as archive:
            archive.getinfo("META-INF/container.xml")
        # curl streams multipart data and keeps the book out of the command line.
        reply = subprocess.run(
            [
                "curl",
                "--disable",
                "--silent",
                "--show-error",
                "--noproxy",
                "*",
                "--max-time",
                "600",
                "--output",
                str(Path(tmp) / "reply"),
                "--write-out",
                "%{http_code}",
                "--form",
                f"file=@{path};type=application/epub+zip",
                story + "/api/books/upload_epub",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        status = int(reply.stdout)
        result = json.loads((Path(tmp) / "reply").read_bytes())
        if status == 201 and type(result.get("id")) is int:
            return result["id"], f"Story Manager book {result['id']}"
        detail = str(result.get("detail", "Unexpected Story Manager response."))
        if status == 409 and "already exists (id=" in detail:
            return None, f"Already imported. {detail}"
        raise ValueError(f"Story Manager returned HTTP {status}. {detail}")


def kindle_metadata(metadata, path):
    identifiers = metadata.get("identifiers") or {}
    asin = identifiers.get("mobi-asin") or identifiers.get("asin")
    series, position = metadata.get("series"), metadata.get("series_index")
    # Match the export to the library record before relying on its filename.
    match = re.search(r" \(([^()]+) Book (\d+(?:\.\d+)?)\)_([A-Z0-9]{10})$", path.stem)
    if match and match[3] == asin and (not series or series == match[1]):
        series = series or match[1]
        if position is None:
            position = float(match[2])
    return series, position, asin


def fill_metadata(client, story, book_id, series, position, asin):
    url = f"{story}/api/books/{book_id}"
    book = api(client, url)
    fields = {}
    if series and (not book.get("series") or book["series"] == series):
        if not book.get("series"):
            fields["series"] = series
        if position is not None and book.get("series_index") is None:
            fields["series_index"] = position
    remote_ids = book.get("metadata_remote_ids") or {}
    if asin and not remote_ids.get("mobi-asin"):
        # Catalog enrichment replaces its own "asin" with provider-validated
        # IDs. Preserve Calibre's original identifier separately across syncs.
        fields["metadata_remote_ids"] = {"asin": asin, **remote_ids, "mobi-asin": asin}
    if fields:
        updated = api(client, url, json.dumps(fields).encode(), method="PUT")
        if any(updated.get(key) != value for key, value in fields.items()):
            raise ValueError(f"Story Manager book {book_id} did not retain its Kindle metadata.")


def process(args, files):
    base = args.calibre.rstrip("/")
    story = args.story_manager.rstrip("/")
    client = opener(base, args.user, getattr(args, "password", None))
    info = api(client, base + "/ajax/library-info")
    library = quote(info["default_library"], safe="")
    formats = api(client, base + "/interface-data/update")["input_formats"]
    supported = {name.lower() for name in formats}
    print(f"Calibre library: {info['library_map'][info['default_library']]}")
    kfx_available = bool({"kfx", "kfx-zip"} & supported)
    print("KFX Input:", "available" if kfx_available else "missing")
    story_client = opener(story, None)
    routes = api(story_client, story + "/openapi.json")["paths"]
    if "post" not in routes.get("/api/books/upload_epub", {}):
        raise ValueError("Story Manager does not advertise its EPUB upload endpoint.")
    if args.check:
        print("Story Manager EPUB upload endpoint: available")
        return int(not kfx_available)
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (STATE / "import.lock").open("a") as lock, sqlite3.connect(STATE / "history.sqlite") as db:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Another Kindle import is running.") from None
        db.execute(
            "CREATE TABLE IF NOT EXISTS imports (source TEXT, digest TEXT, result TEXT, " "PRIMARY KEY (source, digest))"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS pending_series (source TEXT, digest TEXT, book_id INTEGER, "
            "series TEXT, position REAL, asin TEXT, PRIMARY KEY (source, digest))"
        )
        if "asin" not in {col[1] for col in db.execute("PRAGMA table_info(pending_series)")}:
            db.execute("ALTER TABLE pending_series ADD COLUMN asin TEXT")
        source = json.dumps([base, library, story])
        failures = 0
        for path in ([] if getattr(args, "preview_cleanup", False) else files):
            try:
                digest = fingerprint(path)
                pending = db.execute(
                    "SELECT book_id, series, position, asin FROM pending_series " "WHERE source=? AND digest=?",
                    (source, digest),
                ).fetchone()
                if pending:
                    fill_metadata(story_client, story, *pending)
                    db.execute("DELETE FROM pending_series WHERE source=? AND digest=?", (source, digest))
                    db.commit()
                row = db.execute("SELECT result FROM imports WHERE source=? AND digest=?", (source, digest)).fetchone()
                if row:
                    print(f"{path.name} — previously completed")
                    continue
                fmt = path.suffix[1:].lower()
                if fmt not in supported and not (fmt == "kfx-zip" and "kfx" in supported):
                    raise ValueError(f"Calibre has no input plugin for {fmt}. For Kindle KFX files, enable KFX Input.")
                print(f"Importing {path.name} …", flush=True)
                book_id = add_book(client, base, library, path)
                metadata = ensure_epub(client, base, library, book_id)
                story_id, result = send_epub(client, base, library, book_id, story)
                db.execute("INSERT INTO imports VALUES (?, ?, ?)", (source, digest, result))
                series, position, asin = kindle_metadata(metadata, path)
                if story_id and (series or asin):
                    db.execute(
                        "INSERT INTO pending_series VALUES (?, ?, ?, ?, ?, ?)",
                        (source, digest, story_id, series, position, asin),
                    )
                    db.commit()
                    fill_metadata(story_client, story, story_id, series, position, asin)
                    db.execute("DELETE FROM pending_series WHERE source=? AND digest=?", (source, digest))
                db.commit()
                print(f"  {metadata['title']} — {result}")
            except HTTPError as exc:
                if exc.code in (401, 403):
                    raise
                print(f"  {path.name} — {exc}", file=sys.stderr)
                failures += 1
            except (OSError, ValueError, KeyError, zipfile.BadZipFile, subprocess.SubprocessError) as exc:
                print(f"  {path.name} — {exc}", file=sys.stderr)
                failures += 1
        if not getattr(args, "preview_cleanup", False):
            print(f"{len(files) - failures} completed or previously imported; {failures} need attention.")
        if not failures and getattr(args, "cleanup_stage", None):
            clean_verified(
                usb_reader(args.cleanup_stage),
                args.cleanup_stage,
                files,
                db,
                source,
                fingerprint,
                story_client,
                story,
                args.cleanup,
                args.preview_cleanup,
                args.attachment,
            )
        return int(bool(failures))


def load_settings(path):
    try:
        settings = json.loads(path.read_text())
    except FileNotFoundError:
        raise ValueError(f"Copy config.example.json to {path} and set both server URLs.") from None
    if not isinstance(settings, dict):
        raise ValueError(f"Expected a JSON object in {path}.")
    if settings.get("cleanup", "off") not in ("off", "books", "books-and-sidecars"):
        raise ValueError("cleanup must be off, books, or books-and-sidecars.")
    for key in ("calibre", "story_manager"):
        url = urlsplit(settings.get(key) or "")
        if (
            url.scheme not in ("http", "https")
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError(f"Set {key} to a server URL in {path}.")
    return settings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path, nargs="?", help="export folder; default: mounted Kindle dedrm")
    parser.add_argument("--attached", action="store_true", help="scan Kindle-named drives or the connected MTP Kindle")
    parser.add_argument("--preview-cleanup", action="store_true", help="preview cleanup of already imported USB exports")
    parser.add_argument("--check", action="store_true", help="check services and list inputs without importing")
    parser.add_argument("--config", type=Path, default=CONFIG, help="local JSON settings file")
    parser.add_argument("--calibre", help="Calibre Content server URL")
    parser.add_argument("--story-manager")
    parser.add_argument("--user", default=os.environ.get("CALIBRE_USER"), help="Calibre Digest login")
    args = parser.parse_args(argv)
    try:
        settings = load_settings(args.config) if args.config.exists() or not (args.calibre and args.story_manager) else {}
        args.calibre = args.calibre or settings["calibre"]
        args.story_manager = args.story_manager or settings["story_manager"]
        args.password = (
            settings.get("calibre_password") if not args.user or args.user == settings.get("calibre_user") else None
        )
        args.user = args.user or settings.get("calibre_user")
        args.cleanup = settings.get("cleanup", "off")
        args.cleanup_stage = None
        if args.preview_cleanup and (args.check or args.folder):
            parser.error("--preview-cleanup requires a USB Kindle")
        if args.preview_cleanup and args.cleanup == "off":
            args.cleanup = "books"
        with tempfile.TemporaryDirectory(prefix="kindle-import-") as stage:
            if args.folder:
                folders = [args.folder]
            else:
                folders = [
                    folder
                    for folder in Path("/Volumes").glob("*/dedrm")
                    if (not args.attached or "kindle" in folder.parent.name.lower()) and folder.is_dir()
                ]
            if args.preview_cleanup and folders:
                raise ValueError("Cleanup is supported only for a USB Kindle using MTP.")
            if folders:
                files = [path for folder in folders for path in find_sources(folder)]
            else:
                if not args.check and (args.preview_cleanup or args.attached and args.cleanup != "off"):
                    args.cleanup_stage = Path(stage)
                    args.attachment = connected()
                files = usb_sources(Path(stage), args.check)
            if folders or not args.check:
                print(f"{len(files)} Kindle export(s) found.")
                if args.check:
                    for path in files:
                        print(f"  {path}")
            if not files and not args.check:
                return 0
            try:
                return process(args, files)
            except HTTPError as exc:
                if exc.code not in (401, 403) or not exc.url.startswith(args.calibre.rstrip("/") + "/"):
                    raise
                if args.user or args.check or not sys.stdin.isatty():
                    raise ValueError(
                        "Calibre denied access. Use a Content server account with "
                        "write access to this library (--user USERNAME)."
                    ) from exc
                args.user = input("Calibre needs a writable Content server login. Username: ").strip()
                if not args.user:
                    return 1
                return process(args, files)
    except (
        OSError,
        URLError,
        ValueError,
        sqlite3.Error,
        KeyError,
        ParseError,
        zipfile.BadZipFile,
        subprocess.SubprocessError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
