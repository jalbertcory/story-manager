# Automatic Kindle imports on macOS

Connect a Kindle by USB while signed in to your Mac. Within about 15 seconds, the importer checks the Kindle’s top-level `dedrm` folder, sends new exports to Calibre for EPUB conversion, and uploads them to Story Manager. The EPUB carries its title, author, and cover. The importer also fills missing series information and saves the original Kindle book ID when available.

## Set up

1. Install the Xcode command line tools (`xcode-select --install`) and Homebrew’s USB reader (`brew install libmtp`).
2. Enable Calibre’s Content server, give this Mac permission to add books, and install the Calibre KFX Input plugin if you import KFX. The Mac must be able to reach both the Content server and Story Manager.
3. From this directory, run `cp config.example.json config.local.json` and `chmod 600 config.local.json`. Edit the two URLs for your servers. For a Calibre server with Digest authentication, also set `calibre_user` and `calibre_password`. Git ignores this file.
4. Run `/usr/bin/python3 install.py` as your usual Mac user. This installs and starts a per-user launch agent. Run the same command after changing settings or updating the importer. It copies the settings and importer to `~/Library/Application Support/Kindle Story Import/agent/` so they remain available between logins.

## Use and troubleshoot

Connect one Kindle at a time with a data-capable cable and keep it connected until the transfer finishes. Supported exports are KFX-ZIP, KFX, AZW3, MOBI, and EPUB. The agent reads Paperwhite devices over MTP and also recognizes mounted Kindle drives with “Kindle” in the volume name. Reconnect after adding more exports. The importer remembers completed books and retries failures while the Kindle stays connected.

- Follow activity with `tail -f "$HOME/Library/Application Support/Kindle Story Import/import.log"`.
- To check the connection and server setup manually, run `/usr/bin/python3 kindle_import.py --check`. Close other USB file-transfer apps if they have the Kindle open.
- To import an exported folder manually, run `/usr/bin/python3 kindle_import.py "/path/to/dedrm"`.
- To turn automatic imports off, run `launchctl disable "gui/$(id -u)/org.story-manager.kindle-import"` and then `launchctl bootout "gui/$(id -u)/org.story-manager.kindle-import"`. Run the installer again to turn them back on. Import history stays in `~/Library/Application Support/Kindle Story Import/history.sqlite`.
