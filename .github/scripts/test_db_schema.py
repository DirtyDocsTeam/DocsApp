"""Focused tests for the local SQL ERD renderer."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
SPEC = importlib.util.spec_from_file_location("db_schema", SCRIPT_DIR / "db_schema.py")
assert SPEC and SPEC.loader
db_schema = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = db_schema
SPEC.loader.exec_module(db_schema)


class SvgErdLayoutTest(unittest.TestCase):
    def test_segment_crossing_excludes_shared_endpoints(self) -> None:
        self.assertTrue(db_schema.segments_intersect((0, 0), (4, 4), (0, 4), (4, 0)))
        self.assertFalse(db_schema.segments_intersect((0, 0), (4, 0), (4, 0), (4, 4)))

    def test_layout_is_deterministic_and_cards_do_not_overlap(self) -> None:
        root = Path(__file__).resolve().parents[2]
        sql, _, _ = db_schema.collect_sql(root)
        tables = db_schema.parse_ddl(sql)
        first = db_schema.layout_tables(tables)
        second = db_schema.layout_tables(tables)
        self.assertEqual(first, second)
        self.assertFalse(any(
            db_schema.overlaps(item.rect, other.rect)
            for index, item in enumerate(first)
            for other in first[index + 1:]
        ))
        self.assertEqual(0, db_schema.score_layout(first).table_intersections)

    def test_svg_escapes_schema_labels_and_uses_reference_palette(self) -> None:
        table = db_schema.Table("table<&", [db_schema.Column("column<&", "text")])
        svg = db_schema.render_svg([table])
        self.assertIn("table&lt;&amp;", svg)
        self.assertIn('#0e1116', svg)
        self.assertIn('#222c3a', svg)


if __name__ == "__main__":
    unittest.main()
