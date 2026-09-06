"""Offline verification and restore commands for Story Manager backups."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import LIBRARY_PATH
from .database import DATABASE_URL
from .services.backups import BackupError, restore_backup_archive, verify_backup_archive


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify or restore a Story Manager backup.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify = subparsers.add_parser("verify", help="Verify the manifest and every file checksum.")
    verify.add_argument("archive", type=Path)

    restore = subparsers.add_parser("restore", help="Replace the database and library from a verified backup.")
    restore.add_argument("archive", type=Path)
    restore.add_argument("--library-path", type=Path, default=LIBRARY_PATH)
    restore.add_argument("--database-url", default=DATABASE_URL)
    restore.add_argument(
        "--confirm-replace",
        action="store_true",
        help="Required acknowledgement that the current database and library will be replaced.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "verify":
            manifest = verify_backup_archive(args.archive.resolve())
            raw_library = manifest.get("library")
            library = raw_library if isinstance(raw_library, dict) else {}
            print(
                json.dumps(
                    {
                        "status": "verified",
                        "created_at": manifest.get("created_at"),
                        "library_file_count": library.get("file_count", 0),
                        "library_size_bytes": library.get("size_bytes", 0),
                    },
                    indent=2,
                )
            )
            return 0

        if not args.confirm_replace:
            print(
                "Restore refused: pass --confirm-replace after stopping Story Manager to replace the current data.",
                file=sys.stderr,
            )
            return 2
        restore_backup_archive(
            archive_path=args.archive.resolve(),
            database_url=args.database_url,
            library_path=args.library_path.resolve(),
        )
        print("Backup restored. Run database migrations before starting Story Manager.")
        return 0
    except BackupError as exc:
        print(f"Backup operation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
