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
    def test_fk_connection_uses_the_referencing_column_row(self) -> None:
        parent = db_schema.Table("parent", [db_schema.Column("id", "bigint", primary=True)])
        child = db_schema.Table("child", [
            db_schema.Column("id", "bigint", primary=True),
            db_schema.Column("parent_id", "bigint", nullable=False, reference=("parent", "id")),
        ])
        relationship = db_schema.relationships([child, parent])[0]
        positioned = {
            "child": db_schema.PositionedTable(child, db_schema.Rect(0, 0, 200, 86)),
            "parent": db_schema.PositionedTable(parent, db_schema.Rect(300, 0, 200, 60)),
        }
        route = db_schema.relationship_route(relationship, positioned, 1, -1)
        self.assertEqual(34 + 26 + 13, route.start[1])
        self.assertEqual(34 + 13, route.end[1])

    def test_svg_marks_fk_cardinality(self) -> None:
        parent = db_schema.Table("parent", [db_schema.Column("id", "bigint", primary=True)])
        child = db_schema.Table("child", [db_schema.Column("parent_id", "bigint", reference=("parent", "id"))])
        svg = db_schema.render_svg([child, parent])
        self.assertIn('marker-start="url(#zero-many-left)"', svg)
        self.assertNotIn('marker-end=', svg)
        self.assertIn('orient="0"', svg)
        self.assertIn(" C ", svg)
        self.assertNotIn(" L ", svg)

    def test_segment_crossing_excludes_shared_endpoints(self) -> None:
        self.assertTrue(db_schema.segments_intersect((0, 0), (4, 4), (0, 4), (4, 0)))
        self.assertFalse(db_schema.segments_intersect((0, 0), (4, 0), (4, 0), (4, 4)))

    def test_line_clearance_expands_the_collision_area(self) -> None:
        rect = db_schema.Rect(10, 10, 20, 20)
        self.assertTrue(db_schema.segment_crosses_rect((-10, 5), (50, 5), db_schema.expanded_rect(rect)))

    def test_preoptimization_places_leaf_tables_before_their_hubs(self) -> None:
        hub = db_schema.Table("hub", [db_schema.Column("id", "bigint", primary=True)])
        left = db_schema.Table("left", [db_schema.Column("hub_id", "bigint", reference=("hub", "id"))])
        right = db_schema.Table("right", [db_schema.Column("hub_id", "bigint", reference=("hub", "id"))])
        self.assertEqual(["left", "right", "hub"], [table.name for table in db_schema.preoptimized_order([hub, left, right])])
        self.assertEqual(["left", "hub", "right"], [table.name for table in db_schema.preoptimized_order([hub, left, right], "left")])

    def test_vertically_aligned_cards_use_a_fixed_horizontal_force(self) -> None:
        parent = db_schema.Table("parent", [db_schema.Column("id", "bigint", primary=True)])
        child = db_schema.Table("child", [db_schema.Column("parent_id", "bigint", reference=("parent", "id"))])
        relationship = db_schema.relationships([child, parent])[0]
        positioned = {
            "child": db_schema.PositionedTable(child, db_schema.Rect(0, 200, 180, 60)),
            "parent": db_schema.PositionedTable(parent, db_schema.Rect(0, 0, 180, 60)),
        }
        route = db_schema.relationship_route(relationship, positioned, 1, 1)
        self.assertEqual(96, route.start_control[0] - route.start[0])
        self.assertEqual(96, route.end_control[0] - route.end[0])

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
        self.assertTrue(all(
            db_schema.rectangle_gap(item.rect, other.rect) >= db_schema.MIN_CARD_GAP
            for index, item in enumerate(first)
            for other in first[index + 1:]
        ))
        self.assertLessEqual(db_schema.score_layout(first).table_intersections, 1)

    def test_straight_connections_receive_a_small_score_reward(self) -> None:
        parent = db_schema.Table("parent", [db_schema.Column("id", "bigint", primary=True)])
        child = db_schema.Table("child", [db_schema.Column("parent_id", "bigint", reference=("parent", "id"))])
        aligned = [
            db_schema.PositionedTable(child, db_schema.Rect(0, 0, 180, 60)),
            db_schema.PositionedTable(parent, db_schema.Rect(300, 0, 180, 60)),
        ]
        offset = [
            db_schema.PositionedTable(child, db_schema.Rect(0, 0, 180, 60)),
            db_schema.PositionedTable(parent, db_schema.Rect(300, 50, 180, 60)),
        ]
        self.assertEqual(1, db_schema.score_layout(aligned).straight_connections)
        self.assertLess(db_schema.score_layout(aligned).total, db_schema.score_layout(offset).total)

    def test_svg_escapes_schema_labels_and_uses_reference_palette(self) -> None:
        table = db_schema.Table("table<&", [db_schema.Column("column<&", "text")])
        svg = db_schema.render_svg([table])
        self.assertIn("table&lt;&amp;", svg)
        self.assertNotIn('<rect x="-40" y="-40" width=', svg)
        self.assertIn('#222c3a', svg)


if __name__ == "__main__":
    unittest.main()
