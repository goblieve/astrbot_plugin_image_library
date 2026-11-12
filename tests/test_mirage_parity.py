import json
from itertools import chain
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from PIL import Image

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
TEST_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_ROOT))
from store import GalleryStore


def rgba_bytes(image):
    return list(chain.from_iterable(image.convert("RGBA").get_flattened_data()))


def composite_rgba(rgba, background):
    values = []
    for offset in range(0, len(rgba), 4):
        alpha = rgba[offset + 3] / 255.0
        for channel in range(3):
            values.append(round(
                rgba[offset + channel] * alpha + background * (1.0 - alpha)
            ))
    return values


class MirageParityTests(unittest.TestCase):
    def test_browser_and_server_pixel_results_match(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required to run the browser/server parity check.")

        fixture_path = TEST_DIR / "fixtures" / "mirage-parity.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        completed = subprocess.run(
            [node, str(TEST_DIR / "mirage_parity_runner.mjs"), str(fixture_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        browser_results = json.loads(completed.stdout)

        for case in fixture["cases"]:
            with self.subTest(case=case["name"]):
                size = (case["width"], case["height"])
                inner = Image.new("RGB", size)
                cover = Image.new("RGB", size)
                inner.putdata([tuple(pixel) for pixel in case["inner"]])
                cover.putdata([tuple(pixel) for pixel in case["cover"]])
                server_image = GalleryStore._process_mirage_images(
                    inner, cover, case["options"]
                )
                server_rgba = rgba_bytes(server_image)
                browser = browser_results[case["name"]]

                self.assertEqual(len(server_rgba), len(browser["rgba"]))
                for actual, expected in zip(server_rgba, browser["rgba"]):
                    self.assertLessEqual(abs(actual - expected), 1)

                server_white = composite_rgba(server_rgba, 255)
                server_black = composite_rgba(server_rgba, 0)
                for actual, expected in zip(server_white, browser["white"]):
                    self.assertLessEqual(abs(actual - expected), 1)
                for actual, expected in zip(server_black, browser["black"]):
                    self.assertLessEqual(abs(actual - expected), 1)

                if case["name"] == "fully-transparent":
                    for rgba in (server_rgba, browser["rgba"]):
                        self.assertTrue(all(rgba[offset + 3] == 0 for offset in range(0, len(rgba), 4)))
                        self.assertTrue(all(
                            rgba[offset] == rgba[offset + 1] == rgba[offset + 2] == 0
                            for offset in range(0, len(rgba), 4)
                        ))


if __name__ == "__main__":
    unittest.main()