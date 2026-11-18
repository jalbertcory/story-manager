"""Watch macOS USB attachments and run one import for each Kindle connection."""

import time

from kindle_import import main as import_books
from kindle_usb import connected

POLL_SECONDS = 15


def watch(detect, run_import, sleep=time.sleep, clock=time.monotonic):
    previous = frozenset()
    next_attempt = 0
    delay = 60
    print("Waiting for a Kindle USB connection.", flush=True)
    while True:
        devices = detect()
        if devices != previous:
            previous = devices
            next_attempt = 0
            delay = 60
        if devices and clock() >= next_attempt:
            if run_import() == 0:
                next_attempt = float("inf")
            else:
                print(f"Import incomplete. Retrying in {delay} seconds while connected.", flush=True)
                next_attempt = clock() + delay
                delay = min(delay * 2, 600)
        sleep(POLL_SECONDS)


def import_connected():
    print(time.strftime("%Y-%m-%d %H:%M:%S — Kindle connected, checking exports."), flush=True)
    # The process requesting local-network access must survive a denied first
    # connection so macOS can present the permission prompt (Apple TN3179).
    return import_books(["--attached"])


if __name__ == "__main__":
    watch(connected, import_connected)
