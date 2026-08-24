from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.schemas.layout import (  # noqa: E402
    LayoutError,
    TemplateLayoutV1,
    TemplateLayoutV2,
    default_layout,
    default_layout_v1,
    dump_layout,
    validate_layout,
)
from app.services.templates.store import _supported_style_fields  # noqa: E402


def _v2() -> dict:
    return dump_layout(default_layout())


def _block(layout: dict, block_type: str) -> dict:
    return next(block for block in layout["blocks"] if block["type"] == block_type)


def _remove_ref(flow: dict, ref: str) -> None:
    for row in flow["rows"]:
        for column in row["columns"]:
            column["items"] = [item for item in column["items"] if item["ref"] != ref]
        row["columns"] = [column for column in row["columns"] if column["items"]]
    flow["rows"] = [row for row in flow["rows"] if row["columns"]]


class LayoutVersionTests(unittest.TestCase):
    def test_legacy_default_still_validates_as_v1(self) -> None:
        raw = dump_layout(default_layout_v1())
        self.assertIsInstance(validate_layout(raw), TemplateLayoutV1)

        # A missing version is the historical v1 wire format.
        raw.pop("version")
        self.assertIsInstance(validate_layout(raw), TemplateLayoutV1)

    def test_new_default_is_v2_and_round_trips(self) -> None:
        raw = _v2()
        parsed = validate_layout(raw)
        self.assertIsInstance(parsed, TemplateLayoutV2)
        self.assertEqual(dump_layout(parsed), raw)

    def test_unknown_and_non_integer_versions_are_rejected(self) -> None:
        for version in (0, 3, "2", True):
            with self.subTest(version=version), self.assertRaises(LayoutError):
                validate_layout({"version": version})

    def test_v2_disables_legacy_structure_style_fields(self) -> None:
        supported = _supported_style_fields(_v2())
        self.assertIn("bodySize", supported)
        self.assertNotIn("sectionOrder", supported)
        self.assertNotIn("showSummary", supported)
        self.assertNotIn("showHeaderDivider", supported)
        self.assertEqual(_supported_style_fields(dump_layout(default_layout_v1())), [])
        historical_flat_v2 = dump_layout(default_layout_v1())
        historical_flat_v2["version"] = 2
        self.assertEqual(_supported_style_fields(historical_flat_v2), [])


class LayoutV2SemanticTests(unittest.TestCase):
    def test_exact_block_cardinality(self) -> None:
        for mandatory in ("header", "skills", "experience", "education"):
            raw = _v2()
            raw["blocks"] = [
                block for block in raw["blocks"] if block["type"] != mandatory
            ]
            with self.subTest(mandatory=mandatory), self.assertRaises(LayoutError):
                validate_layout(raw)

        raw = _v2()
        raw["blocks"] = [
            block for block in raw["blocks"] if block["type"] != "summary"
        ]
        validate_layout(raw)

        raw = _v2()
        duplicate = copy.deepcopy(_block(raw, "header"))
        duplicate["id"] = "duplicate-header"
        duplicate["columnId"] = "page-body-main"
        duplicate["order"] = 99
        # Inner ids also need to be distinct so the semantic duplicate is the
        # rule under test.
        for row in duplicate["contentFlow"]["rows"]:
            row["id"] += "-copy"
            for column in row["columns"]:
                column["id"] += "-copy"
                for item in column["items"]:
                    item["id"] += "-copy"
        raw["blocks"] = [
            block for block in raw["blocks"] if block["type"] != "summary"
        ]
        raw["blocks"].append(duplicate)
        with self.assertRaisesRegex(LayoutError, "Duplicate semantic blocks"):
            validate_layout(raw)

    def test_content_and_repeated_item_scopes(self) -> None:
        raw = _v2()
        _remove_ref(_block(raw, "header")["contentFlow"], "contactInfo")
        with self.assertRaisesRegex(LayoutError, "missing refs: contactInfo"):
            validate_layout(raw)

        raw = _v2()
        _remove_ref(_block(raw, "experience")["itemFlow"], "companySummary")
        with self.assertRaisesRegex(LayoutError, "missing refs: companySummary"):
            validate_layout(raw)

        # Location is optional in both repeating group templates.
        raw = _v2()
        _remove_ref(_block(raw, "experience")["itemFlow"], "location")
        _remove_ref(_block(raw, "education")["itemFlow"], "location")
        validate_layout(raw)

        raw = _v2()
        item = _block(raw, "skills")["contentFlow"]["rows"][0]["columns"][0]["items"][1]
        item["ref"] = "companyName"
        with self.assertRaisesRegex(LayoutError, "invalid refs: companyName"):
            validate_layout(raw)

    def test_flow_widths_column_limit_ids_and_gap_dividers(self) -> None:
        raw = _v2()
        row = _block(raw, "header")["contentFlow"]["rows"][0]
        row["columns"][0]["widthPct"] = 90
        with self.assertRaisesRegex(LayoutError, "must total 100%"):
            validate_layout(raw)

        raw = _v2()
        row = _block(raw, "header")["contentFlow"]["rows"][0]
        row["columns"] = [
            {"id": "three-a", "widthPct": 34, "items": [{"id": "a", "ref": "name"}]},
            {"id": "three-b", "widthPct": 33, "items": [{"id": "b", "ref": "title"}]},
            {"id": "three-c", "widthPct": 33, "items": [{"id": "c", "ref": "contactInfo"}]},
        ]
        with self.assertRaises(LayoutError):
            validate_layout(raw)

        raw = _v2()
        _block(raw, "summary")["id"] = "block-header"
        with self.assertRaisesRegex(LayoutError, "Duplicate block ids|Duplicate id"):
            validate_layout(raw)

        raw = _v2()
        first = _block(raw, "header")["contentFlow"]["rows"][0]["columns"][0]["items"][0]
        first["dividerBefore"] = {"kind": "line"}
        with self.assertRaisesRegex(LayoutError, "first item"):
            validate_layout(raw)

    def test_entry_metadata_supports_inline_groups_and_four_aligned_cells(self) -> None:
        raw = _v2()
        # Education, not experience: experience's metadata row is down to 3
        # items (companyName, period, location) now that roleTitle moved to
        # its own row below the company name (see default_layout() in
        # app/schemas/layout.py). Education's is still 2+2, which is what
        # this test -- a generic "N items split into N aligned cells"
        # capability check, not something specific to either block -- needs.
        education = _block(raw, "education")
        metadata_row = education["itemFlow"]["rows"][0]
        self.assertEqual(
            [column["mode"] for column in metadata_row["columns"]],
            ["inline", "inline"],
        )
        self.assertEqual(
            [column["align"] for column in metadata_row["columns"]],
            ["left", "right"],
        )

        metadata_items = [
            item
            for column in metadata_row["columns"]
            for item in column["items"]
        ]
        for item in metadata_items:
            item.pop("dividerBefore", None)
        metadata_row["columns"] = [
            {
                "id": f"metadata-cell-{index}",
                "widthPct": 25,
                "mode": "stack",
                "align": align,
                "items": [item],
            }
            for index, (item, align) in enumerate(
                zip(metadata_items, ("left", "center", "center", "right")),
                start=1,
            )
        ]
        validate_layout(raw)

        raw = _v2()
        # rows[1] is roleTitle's own row now (see default_layout()); the
        # companySummary row this test actually targets moved to rows[2].
        summary_column = _block(raw, "experience")["itemFlow"]["rows"][2]["columns"][0]
        summary_column["mode"] = "inline"
        with self.assertRaisesRegex(LayoutError, "inline columns"):
            validate_layout(raw)

        raw = _v2()
        inline_column = _block(raw, "education")["itemFlow"]["rows"][0]["columns"][0]
        inline_column["items"][1].pop("dividerBefore")
        with self.assertRaisesRegex(LayoutError, "require dividers"):
            validate_layout(raw)

        raw = _v2()
        _block(raw, "education")["itemFlow"]["rows"][0]["columns"][0]["align"] = "justify"
        with self.assertRaises(LayoutError):
            validate_layout(raw)

        raw = _v2()
        item_flow = _block(raw, "experience")["itemFlow"]
        items_by_ref = {
            item["ref"]: copy.deepcopy(item)
            for row in item_flow["rows"]
            for column in row["columns"]
            for item in column["items"]
        }
        compact_plus_prose = [
            items_by_ref[ref]
            for ref in ("companyName", "roleTitle", "period", "companySummary")
        ]
        for item in compact_plus_prose:
            item.pop("dividerBefore", None)
        item_flow["rows"] = [
            {
                "id": "invalid-four-cell-row",
                "columns": [
                    {
                        "id": f"prose-cell-{index}",
                        "widthPct": 25,
                        "items": [item],
                    }
                    for index, item in enumerate(compact_plus_prose)
                ],
            },
            {
                "id": "bullets-row",
                "columns": [
                    {
                        "id": "bullets-column",
                        "widthPct": 100,
                        "items": [items_by_ref["bullets"]],
                    }
                ],
            },
        ]
        with self.assertRaisesRegex(LayoutError, "3-4 column rows"):
            validate_layout(raw)

    def test_divider_characters(self) -> None:
        for character in ("·", "|", " - "):
            raw = _v2()
            raw["dividerDefaults"]["character"] = character
            validate_layout(raw)

        for character in ("", "   ", "four", "\n"):
            raw = _v2()
            raw["dividerDefaults"]["character"] = character
            with self.subTest(character=repr(character)), self.assertRaises(LayoutError):
                validate_layout(raw)

        raw = _v2()
        summary_items = _block(raw, "summary")["contentFlow"]["rows"][0][
            "columns"
        ][0]["items"]
        summary_items[1]["dividerBefore"] = {"kind": "character"}
        validate_layout(raw)  # inherits dividerDefaults.character

        raw = _v2()
        summary_items = _block(raw, "summary")["contentFlow"]["rows"][0]["columns"][0]["items"]
        summary_items[1]["dividerBefore"] = {
            "kind": "line",
            "spaceBeforeIn": 0.15,
            "spaceAfterIn": 0.23,
        }
        parsed = validate_layout(raw)
        summary = next(block for block in parsed.blocks if block.type == "summary")
        divider = summary.contentFlow.items()[1].dividerBefore
        self.assertEqual((divider.spaceBeforeIn, divider.spaceAfterIn), (0.15, 0.23))

        raw = _v2()
        summary_items = _block(raw, "summary")["contentFlow"]["rows"][0]["columns"][0]["items"]
        summary_items[1]["dividerBefore"] = {"kind": "none", "spaceBeforeIn": 0.1}
        validate_layout(raw)

    def test_block_and_item_styles_are_normalized(self) -> None:
        raw = _v2()
        header = _block(raw, "header")
        header["style"] = {"bodySize": "12", "personalOrder": ["email"]}
        header["contentFlow"]["rows"][0]["columns"][0]["items"][0]["style"] = {
            "nameSize": "24"
        }

        parsed = validate_layout(raw)
        parsed_header = next(block for block in parsed.blocks if block.type == "header")
        self.assertEqual(parsed_header.style["bodySize"], 12.0)
        self.assertEqual(
            parsed_header.style["personalOrder"],
            ["email", "address", "phone", "birthday"],
        )
        self.assertEqual(parsed_header.contentFlow.items()[0].style["nameSize"], 24.0)

        raw = _v2()
        _block(raw, "header")["style"] = {"fontFamily": "Montserrat"}
        parsed = validate_layout(raw)
        parsed_header = next(block for block in parsed.blocks if block.type == "header")
        self.assertEqual(parsed_header.style["fontFamily"], "Montserrat")

    def test_section_visibility_and_page_geometry(self) -> None:
        raw = _v2()
        contact = next(
            item
            for item in _block(raw, "header")["contentFlow"]["rows"][0]["columns"][0]["items"]
            if item["ref"] == "contactInfo"
        )
        contact["hidden"] = True
        raw["page"].update(
            {
                "size": "a4",
                "marginTopIn": 0.4,
                "marginBottomIn": 0.45,
                "marginLeftIn": 0.5,
                "marginRightIn": 0.55,
            }
        )
        parsed = validate_layout(raw)
        parsed_contact = next(
            item
            for block in parsed.blocks
            if block.type == "header"
            for item in block.contentFlow.items()
            if item.ref == "contactInfo"
        )
        self.assertTrue(parsed_contact.hidden)
        self.assertEqual(parsed.page.size, "a4")
        self.assertEqual(parsed.page.marginRightIn, 0.55)

        raw = _v2()
        raw["page"].update({"size": "statement", "marginLeftIn": 2, "marginRightIn": 2})
        with self.assertRaisesRegex(LayoutError, "content width"):
            validate_layout(raw)

    def test_individual_section_and_divider_colors(self) -> None:
        raw = _v2()
        summary_items = _block(raw, "summary")["contentFlow"]["rows"][0][
            "columns"
        ][0]["items"]
        summary_items[1]["style"] = {"bodyColor": "#123ABC"}
        summary_items[1]["dividerBefore"] = {
            "kind": "line",
            "color": "#A52A2A",
        }
        raw["page"]["regions"][1]["dividerBefore"] = {
            "kind": "line",
            "color": "#8B008B",
        }
        body_columns = raw["page"]["regions"][1]["columns"]
        body_columns[0]["widthPct"] = 50
        body_columns.append({
            "id": "page-body-secondary",
            "widthPct": 50,
            "dividerBefore": {
                "kind": "character",
                "color": "#006400",
            },
        })

        parsed = validate_layout(raw)
        summary = next(block for block in parsed.blocks if block.type == "summary")
        content = summary.contentFlow.items()[1]
        self.assertEqual(content.style["bodyColor"], "#123ABC")
        self.assertEqual(content.dividerBefore.color, "#A52A2A")
        self.assertEqual(parsed.page.regions[1].dividerBefore.color, "#8B008B")
        self.assertEqual(parsed.page.regions[1].columns[1].dividerBefore.color, "#006400")

        raw = _v2()
        raw["page"]["regions"][1]["dividerBefore"] = {
            "kind": "line",
            "color": "red",
        }
        with self.assertRaises(LayoutError):
            validate_layout(raw)

    def test_only_block_titles_accept_bounded_label_props(self) -> None:
        raw = _v2()
        title_item = _block(raw, "summary")["contentFlow"]["rows"][0]["columns"][0]["items"][0]
        title_item["props"] = {"label": "Profile"}
        parsed = validate_layout(raw)
        summary = next(block for block in parsed.blocks if block.type == "summary")
        self.assertEqual(summary.contentFlow.items()[0].props, {"label": "Profile"})

        raw = _v2()
        title_item = _block(raw, "summary")["contentFlow"]["rows"][0]["columns"][0]["items"][0]
        title_item["props"] = {"label": "x" * 121}
        with self.assertRaises(LayoutError):
            validate_layout(raw)

        raw = _v2()
        title_item = _block(raw, "summary")["contentFlow"]["rows"][0]["columns"][0]["items"][0]
        title_item["props"] = {"label": ""}
        parsed = validate_layout(raw)
        summary = next(block for block in parsed.blocks if block.type == "summary")
        self.assertEqual(summary.contentFlow.items()[0].props, {"label": ""})

        raw = _v2()
        content_item = _block(raw, "summary")["contentFlow"]["rows"][0]["columns"][0]["items"][1]
        content_item["props"] = {"label": "not allowed"}
        with self.assertRaisesRegex(LayoutError, "does not take props"):
            validate_layout(raw)


if __name__ == "__main__":
    unittest.main()
