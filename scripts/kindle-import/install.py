"""Install or update the Kindle importer as a macOS login agent."""

import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile

from kindle_import import CONFIG, STATE, build_reader, load_settings


def install():
    if sys.platform != "darwin" or os.getuid() == 0:
        raise ValueError("Run the installer on macOS as the user who connects the Kindle.")
    load_settings(CONFIG)
    label = "org.story-manager.kindle-import"
    domain = f"gui/{os.getuid()}"
    target = f"{domain}/{label}"
    runtime = STATE / "agent"
    runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
    plist = Path.home() / "Library" / "LaunchAgents" / (label + ".plist")
    plist.parent.mkdir(parents=True, exist_ok=True)
    log = STATE / "import.log"
    with tempfile.TemporaryDirectory(dir=runtime) as tmp:
        stage = Path(tmp)
        build_reader(stage / "kindle-reader")
        for name in ("watch.py", "kindle_import.py", "cleanup.py", "kindle_usb.py", CONFIG.name):
            shutil.copyfile(Path(__file__).with_name(name), stage / name)
            (stage / name).chmod(0o600)
        definition = {
            "Label": label,
            "ProgramArguments": ["/usr/bin/python3", "-u", str(runtime / "watch.py")],
            "KeepAlive": True,
            "RunAtLoad": True,
            "ThrottleInterval": 30,
            "StandardOutPath": str(log),
            "StandardErrorPath": str(log),
        }
        if subprocess.run(["launchctl", "print", target], capture_output=True).returncode == 0:
            subprocess.run(["launchctl", "bootout", target], check=True)
        for path in stage.iterdir():
            path.replace(runtime / path.name)
        with tempfile.NamedTemporaryFile(dir=plist.parent, delete=False) as f:
            plistlib.dump(definition, f)
        Path(f.name).replace(plist)
    subprocess.run(["launchctl", "enable", target], check=True)
    subprocess.run(["launchctl", "bootstrap", domain, str(plist)], check=True)
    print(f"Automatic Kindle imports enabled. Activity log: {log}")


if __name__ == "__main__":
    try:
        install()
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        sys.exit(str(exc))
