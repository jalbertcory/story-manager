# Automatic Kindle imports on macOS

Connect a Kindle by USB while signed in to your Mac. Within about 15 seconds, the importer checks the Kindle’s top-level `dedrm` folder, sends new exports to Calibre for EPUB conversion, and uploads them to Story Manager. The EPUB carries its title, author, and cover. The importer also fills missing series information and saves the original Kindle book ID when available.

## Set up

1. Install the Xcode command line tools (`xcode-select --install`) and Homebrew’s USB reader (`brew install libmtp`).
2. Enable Calibre’s Content server, give this Mac permission to add books, and install the Calibre KFX Input plugin if you import KFX. The Mac must be able to reach both the Content server and Story Manager.
3. From this directory, run `cp config.example.json config.local.json` and `chmod 600 config.local.json`. Edit the two URLs for your servers. For a Calibre server with Digest authentication, also set `calibre_user` and `calibre_password`. Git ignores this file.
4. Run `/usr/bin/python3 install.py` as your usual Mac user. This installs and starts a per-user launch agent. Run the same command after changing settings or updating the importer. It copies the settings and importer to `~/Library/Application Support/Kindle Story Import/agent/` so they remain available between logins.

## Use and troubleshoot

Connect one Kindle at a time with a data-capable cable and keep it connected until the transfer finishes. Supported exports are KFX-ZIP, KFX, AZW3, MOBI, and EPUB. The agent reads Paperwhite devices over MTP and also recognizes mounted Kindle drives with “Kindle” in the volume name. Reconnect after adding more exports. The importer remembers completed books and retries failures while the Kindle stays connected.

- On the first connection, allow Python to access the local network if macOS asks. If the log reports “No route to host” while the servers are reachable, check Python under **System Settings → Privacy & Security → Local Network**. Leave the Kindle connected for the automatic retry.
- Follow activity with `tail -f "$HOME/Library/Application Support/Kindle Story Import/import.log"`.
- To check the connection and server setup manually, run `/usr/bin/python3 kindle_import.py --check`. Close other USB file-transfer apps if they have the Kindle open.
- To import an exported folder manually, run `/usr/bin/python3 kindle_import.py "/path/to/dedrm"`.
- To turn automatic imports off, run `launchctl disable "gui/$(id -u)/org.story-manager.kindle-import"` and then `launchctl bootout "gui/$(id -u)/org.story-manager.kindle-import"`. Run the installer again to turn them back on. Import history stays in `~/Library/Application Support/Kindle Story Import/history.sqlite`.

## Clean the Kindle after import

Run `/usr/bin/python3 kindle_import.py --preview-cleanup` to list what would be removed from a connected MTP Kindle. Cleanup is optional. Set `cleanup` in `config.local.json` and rerun `/usr/bin/python3 install.py` to apply your choice. Installing starts the watcher immediately, including for a Kindle already plugged in.

| Setting | What happens after a successful USB import |
| --- | --- |
| `off` (default) | Keep all files. |
| `books` | Remove verified exports from `dedrm` and matching book files from `documents/Downloads/Items01` or another Kindle `Downloads/Items` folder. Keep the book’s `.sdr` folder. |
| `books-and-sidecars` | Also remove the matching `.sdr` folder and its contents, which may include local annotations and reading progress. |

The importer checks each export’s content against its completed import history, downloads the saved EPUB from Story Manager, and verifies its Kindle ID. Only an exact book filename stem, including that ID, qualifies a download for removal. A changed export, an unrelated dictionary, or a book without a verifiable ID stays on the Kindle. Cleanup removes on-device copies permanently. Mounted drives and manual folder imports stay read-only.
