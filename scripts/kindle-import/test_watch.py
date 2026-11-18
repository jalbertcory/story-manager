import itertools
import unittest

from kindle_usb import kindle_connections
from watch import watch


class WatchTests(unittest.TestCase):
    def test_only_kindle_connections(self):
        def device(vendor, product, name, entry):
            return {"idVendor": vendor, "idProduct": product, "USB Product Name": name, "IORegistryEntryID": entry}

        tree = {
            "IORegistryEntryChildren": [
                device(0x1949, 0x9981, "Amazon device", 41),
                device(0x1949, 1, "Kindle", 42),
                device(0x1949, 2, "Fire TV", 43),
                device(1, 0x9981, "USB hub", 44),
            ]
        }
        self.assertEqual(kindle_connections(tree), {41, 42})

    def test_retry_and_reattach(self):
        # A missed unplug between polls still gives the new connection a new ID.
        samples = iter([(0, ()), (15, (1,)), (30, (1,)), (75, (1,)), (90, (1,)), (105, (2,)), (120, ()), (135, (3,))])
        attempts = []
        outcomes = itertools.chain([1], itertools.repeat(0))
        now = 0

        def detect():
            nonlocal now
            now, devices = next(samples)
            return frozenset(devices)

        def run_import():
            attempts.append(now)
            return next(outcomes)

        with self.assertRaises(StopIteration):
            watch(detect, run_import, sleep=lambda _: None, clock=lambda: now)
        self.assertEqual(attempts, [15, 75, 105, 135])


if __name__ == "__main__":
    unittest.main()
