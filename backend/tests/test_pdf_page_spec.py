from __future__ import annotations

import sys
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.pdf.generator import _page_spec  # noqa: E402


class PdfPageSpecTests(unittest.TestCase):
    def test_template_geometry_reaches_playwright_options(self) -> None:
        width, height, margins = _page_spec(
            {
                "layout": {
                    "version": 2,
                    "page": {
                        "size": "a4",
                        "marginTopIn": 0.4,
                        "marginBottomIn": 0.5,
                        "marginLeftIn": 0.6,
                        "marginRightIn": 0.7,
                    },
                }
            }
        )
        self.assertEqual((width, height), (8.27, 11.69))
        self.assertEqual(
            margins,
            {"top": 0.4, "bottom": 0.5, "left": 0.6, "right": 0.7},
        )

    def test_legacy_payload_uses_letter_defaults(self) -> None:
        width, height, margins = _page_spec({"layout": None})
        self.assertEqual((width, height), (8.5, 11))
        self.assertEqual(margins["top"], 0.7)
        self.assertEqual(margins["left"], 0.65)


if __name__ == "__main__":
    unittest.main()
