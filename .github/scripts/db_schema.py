#!/usr/bin/env python3
"""Схема БД из Liquibase-чанжлога: единый DDL, SVG ERD и Markdown со связями.

Источник правды по схеме — чанжлог в `backend/api/src/main/resources/db/changelog/`.
Скрипт разворачивает master-файл (`include`, `includeAll`, `sqlFile`) и собирает из него три
производных артефакта:

  * `documentation/design/db.sql` — единый DDL для чтения и прогона в psql;
  * `documentation/design/erd.md` — страница диаграммы и таблица внешних ключей;
  * `documentation/design/schema.svg` — векторная диаграмма; Mermaid доступен через --mermaid.

Использование:
  python3 .github/scripts/db_schema.py            # пересобрать db.sql и erd.md
  python3 .github/scripts/db_schema.py --check     # проверить, что артефакты соответствуют чанжлогу
  python3 .github/scripts/db_schema.py --verify    # прогнать DDL на чистой PostgreSQL в docker
  python3 .github/scripts/db_schema.py --mermaid   # только напечатать erDiagram

Зависимости — стандартная библиотека Python 3.11+. `--verify` дополнительно требует docker.
"""
from __future__ import annotations

import argparse
import html
import json
import math
import re
import subprocess
import sys
import time
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from shutil import which

from yaml_subset import YamlSubset
from sql_schema import Column, Table, parse_ddl, column_references
from erd_optimizer import (LayoutOptions, optimize_grid, route_all, hits_rect, overlap_length, trim_ports,
                           smooth_terminal_path, merge_junctions, junction_conflicts, endpoint_keys, shared_corner_radii,
                           rounded_orthogonal_path, TRANSPORT_GAP)

CHANGELOG_DIR = "backend/api/src/main/resources/db/changelog"
MASTER = CHANGELOG_DIR + "/db.changelog-master.yaml"
DB_SQL = "documentation/design/db.sql"
ERD_MD = "documentation/design/erd.md"
ERD_SVG = "documentation/design/schema.svg"
LAYOUT_YAML = "documentation/design/layout.yaml"

POSTGRES_IMAGE = "postgres:16-alpine"
PG_CONTAINER = "docsapp-dbcheck-" + uuid.uuid4().hex[:12]

SQL_HEADER = """-- DocsApp: схема базы данных.
--
-- Файл сгенерирован из Liquibase-чанжлога {changelog}/
-- Пересобрать: `make db-schema`. ERD: documentation/design/erd.md (`make db-erd`).
-- Руками не правим: правки перезапишутся, менять нужно чанжлог.
--
-- Состав:
{parts}
"""

ERD_HEADER = """# ERD: модель данных

Схема БД диаграммой. Источник правды — Liquibase-чанжлог
`{changelog}/`: из него собираются и [`db.sql`](db.sql), и диаграмма ниже
(`make db-schema`, `make db-erd`). Руками файл не правим — меняем чанжлог.

![ERD: модель данных](schema.svg)

Текстовый Mermaid-вариант доступен через `python3 .github/scripts/db_schema.py --mermaid`;
в опубликованной документации используется локально сгенерированный SVG.

## Связи

Внешние ключи в том виде, в каком они объявлены в схеме: `ребёнок.колонка` → `родитель.колонка`.

{relations}
"""


# ─────────────────────────── чанжлог ───────────────────────────

def is_true(value) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "on"}


def git_repo_root(start: Path) -> Path:
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=str(start),
                             capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return start.resolve()
    return Path(out)


def load_changelog(root: Path) -> tuple[list[Path], list[str]]:
    """Разворачивает master-чанжлог в упорядоченный список SQL-файлов."""
    master = root / MASTER
    if not master.is_file():
        raise SystemExit("Не найден master-чанжлог %s" % MASTER)
    document = YamlSubset(master.read_text(encoding="utf-8"), MASTER).parse()
    entries = document.get("databaseChangeLog")
    if not isinstance(entries, list):
        raise SystemExit("%s: ожидался список `databaseChangeLog`" % MASTER)

    changelog_dir = (root / CHANGELOG_DIR).resolve()
    # пути в чанжлоге задаются от classpath Liquibase (src/main/resources), поэтому пробуем
    # каталог чанжлога, затем корень ресурсов и только потом корень репозитория
    resources_root = changelog_dir.parent.parent
    files: list[Path] = []
    warnings: list[str] = []

    def resolve(name: str, relative_to_changelog: bool) -> Path | None:
        candidates = ([changelog_dir / name] if relative_to_changelog
                      else [resources_root / name, root / name, changelog_dir / name])
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved.is_file():
                return resolved
        return None

    for entry in entries:
        if not isinstance(entry, dict):
            warnings.append("пропущена запись чанжлога: %r" % (entry,))
            continue
        if "include" in entry:
            spec = entry["include"] or {}
            name = str(spec.get("file") or "").strip()
            if not name:
                warnings.append("`include` без `file` — пропущен")
                continue
            path = resolve(name, is_true(spec.get("relativeToChangelogFile")))
            if path is not None:
                files.append(path)
            else:
                warnings.append("`include` указывает на отсутствующий файл %s" % name)
        elif "includeAll" in entry:
            spec = entry["includeAll"] or {}
            name = str(spec.get("path") or "").strip()
            base = changelog_dir if is_true(spec.get("relativeToChangelogFile")) else resources_root
            directory = (base / name).resolve()
            found = sorted(directory.glob("*.sql")) if directory.is_dir() else []
            if found:
                files.extend(found)
            else:
                warnings.append("`includeAll` не нашёл SQL в %s" % name)
        elif "changeSet" in entry:
            spec = entry["changeSet"] or {}
            change_id = "%s:%s" % (spec.get("author", "?"), spec.get("id", "?"))
            sql_file = str(spec.get("sqlFile") or "").strip()
            changes = spec.get('changes', [])
            if changes:
                for change in changes:
                    if not isinstance(change, dict) or 'sqlFile' not in change:
                        raise ValueError(f'Unsupported Liquibase change in {change_id}')
                    source = change['sqlFile']
                    source = {'path': source} if isinstance(source, str) else source
                    name = source.get('path', '')
                    path = resolve(name, is_true(source.get('relativeToChangelogFile')))
                    if path is None:
                        raise ValueError(f'Missing SQL file in {change_id}: {name}')
                    files.append(path)
                continue
            if sql_file:
                path = resolve(sql_file, True) or resolve(sql_file, False)
                if path is not None:
                    files.append(path)
                else:
                    warnings.append("changeSet %s: нет файла %s" % (change_id, sql_file))
            elif spec.get("sql"):
                warnings.append("changeSet %s содержит инлайновый SQL — перенесите его в файл, "
                                "чтобы он попал в db.sql" % change_id)
            else:
                warnings.append("changeSet %s без SQL — пропущен" % change_id)
        else:
            warnings.append("неизвестная запись чанжлога: %s" % ", ".join(sorted(entry)))
    if warnings:
        raise ValueError('Cannot build a complete schema: ' + '; '.join(warnings))
    return files, warnings


LIQUIBASE_DIRECTIVE = {"liquibase", "changeset", "rollback", "preconditions", "comment",
                       "property", "validchecksum"}


def reindent(line: str) -> str:
    """Глубокие отступы чанжлога подрезаем до 4 пробелов: DDL читают люди, а не колонки."""
    stripped = line.lstrip(" ")
    if not stripped:
        return ""
    return " " * min(len(line) - len(stripped), 4) + stripped


def clean_sql(text: str) -> str:
    """Убирает служебные комментарии Liquibase, выравнивает отступы и лишние пустые строки."""
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            directive = stripped[2:].strip().split(":")[0].split(" ")[0].lower()
            if directive in LIQUIBASE_DIRECTIVE:
                continue
        lines.append(reindent(line.rstrip()))

    result: list[str] = []
    for line in lines:
        if line or (result and result[-1]):
            result.append(line)
    while result and not result[-1]:
        result.pop()
    return "\n".join(result)


def plural_lines(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return "строка"
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return "строки"
    return "строк"


def collect_sql(root: Path) -> tuple[str, list[Path], list[str]]:
    files, warnings = load_changelog(root)
    if not files:
        raise SystemExit("Чанжлог не содержит SQL-файлов — собирать нечего")

    parts = []
    for path in files:
        try:
            parts.append((path, clean_sql(path.read_text(encoding="utf-8"))))
        except (OSError, UnicodeDecodeError) as exc:
            warnings.append("%s не читается: %s" % (path, exc))
    return "\n\n".join(sql for _, sql in parts), [path for path, _ in parts], warnings


def build_sql(root: Path, sql: str, files: list[Path]) -> str:
    listing = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        try:
            lines = len(clean_sql(path.read_text(encoding="utf-8")).splitlines())
        except (OSError, UnicodeDecodeError):
            continue
        listing.append("--   %s — %d %s" % (rel, lines, plural_lines(lines)))
    header = SQL_HEADER.format(changelog=CHANGELOG_DIR, parts="\n".join(listing))
    return header + "\n" + sql + "\n"


# ─────────────────────────── Mermaid ───────────────────────────

MERMAID_TYPE_RE = re.compile(r"[^A-Za-z0-9_\-()\[\]]+")


def mermaid_type(raw: str) -> str:
    """Mermaid допускает в типе буквы, цифры и `- _ ( ) [ ]`; остальное схлопываем в `_`."""
    value = MERMAID_TYPE_RE.sub("_", raw.strip()).strip("_")
    if not value:
        return "text"
    if not value[0].isalpha():
        return "t_" + value
    return value


def mermaid_name(raw: str) -> str:
    return re.sub(r"[^A-Za-z0-9_\-()\[\]]+", "_", raw.strip()) or "column"


def render_mermaid(tables: list[Table]) -> str:
    lines = ["erDiagram"]
    for table in tables:
        lines.append("    %s {" % table.name)
        for column in table.columns:
            keys = []
            if column.primary:
                keys.append("PK")
            if column.reference:
                keys.append("FK")
            suffix = (" " + ", ".join(keys)) if keys else ""
            lines.append("        %s %s%s" % (mermaid_type(column.type),
                                              mermaid_name(column.name), suffix))
        lines.append("    }")
    for table in tables:
        for column in table.columns:
            for parent, parent_column in column_references(column):
                # у родителя ровно одна запись, у ребёнка — много; nullable FK допускает ноль
                left = "|o" if column.nullable else "||"
                lines.append('    %s %s--o{ %s : "%s.%s"' % (
                    parent, left, table.name, table.name, column.name))
    return "\n".join(lines)


def render_relations(tables: list[Table]) -> str:
    rows = ["| Ребёнок | Колонка | Родитель | Колонка | Обязательная |",
            "|---|---|---|---|---|"]
    found = False
    for table in tables:
        for column in table.columns:
            for parent, parent_column in column_references(column):
                found = True
                rows.append("| `%s` | `%s` | `%s` | `%s` | %s |" % (
                    table.name, column.name, parent, parent_column,
                    "нет" if column.nullable else "да"))
    return "\n".join(rows) if found else "_Внешних ключей нет._"


def build_erd(tables: list[Table]) -> str:
    return ERD_HEADER.format(changelog=CHANGELOG_DIR, diagram=render_mermaid(tables),
                             relations=render_relations(tables))


def load_fixed_positions(root: Path, tables: list[Table]) -> dict[str, tuple[float, float]]:
    path = root / LAYOUT_YAML
    if not path.is_file():
        return {}
    document = YamlSubset(path.read_text(encoding="utf-8"), LAYOUT_YAML).parse()
    positions = document.get("positions", {})
    if not isinstance(positions, dict):
        raise SystemExit("%s: ожидался словарь positions" % LAYOUT_YAML)
    known = {table.name for table in tables}
    unknown = sorted(set(positions) - known)
    if unknown:
        raise SystemExit("%s: неизвестные таблицы: %s" % (LAYOUT_YAML, ", ".join(unknown)))
    result = {}
    for name, value in positions.items():
        if not isinstance(value,dict):
            raise SystemExit("%s: %s требует числовые x и y" % (LAYOUT_YAML, name))
        try:
            point=float(value['x']),float(value['y'])
            if not all(math.isfinite(v) for v in point):
                raise ValueError()
        except (KeyError,TypeError,ValueError):
            raise SystemExit("%s: %s требует конечные числовые x и y" % (LAYOUT_YAML,name))
        result[name]=point
    return result


def load_layout_options(root: Path, steps: int | None = None, routing_passes: int | None = None,
                        seed: int | None = None) -> LayoutOptions:
    path=root / LAYOUT_YAML
    document=YamlSubset(path.read_text(encoding='utf-8'),LAYOUT_YAML).parse() if path.is_file() else {}
    settings=document.get('optimization',{})
    if not isinstance(settings,dict):
        raise ValueError('layout.yaml: optimization must be a mapping')
    unknown=set(settings)-{'steps','routing_passes','seed'}
    if unknown:
        raise ValueError('Unknown layout optimization keys: '+', '.join(sorted(unknown)))
    # The shared YAML subset reader intentionally leaves scalar values as strings.
    values={key:int(value) if isinstance(value,str) and re.fullmatch(r'[+-]?\d+',value) else value
            for key,value in settings.items()}
    for key,value in (('steps',steps),('routing_passes',routing_passes),('seed',seed)):
        if value is not None:
            values[key]=value
    return LayoutOptions(**values)


# ─────────────────────────── SVG ERD ───────────────────────────

CARD_HEADER_HEIGHT = 34
CARD_ROW_HEIGHT = 26
CARD_GUTTER = 56
LAYOUT_PADDING = 40
MIN_CARD_GAP = 48
LINE_BLOCK_CLEARANCE = 12
CONNECTOR_CONTROL_OFFSET = 48
VERTICAL_CONNECTOR_CONTROL_OFFSET = 96


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    width: float
    height: float

    @property
    def center(self) -> tuple[float, float]:
        return self.x + self.width / 2, self.y + self.height / 2


@dataclass(frozen=True)
class PositionedTable:
    table: Table
    rect: Rect


@dataclass(frozen=True)
class LayoutScore:
    table_intersections: int
    line_intersections: int
    straight_connections: int
    nearest_gap: float
    average_gap: float

    @property
    def total(self) -> float:
        return (10 * self.table_intersections + 2 * self.line_intersections +
                .1 * self.nearest_gap + .01 * self.average_gap -
                1 * self.straight_connections)


@dataclass(frozen=True)
class Relationship:
    child: str
    column: str
    parent: str
    parent_column: str
    nullable: bool


@dataclass(frozen=True)
class RelationshipRoute:
    relationship: Relationship
    start: tuple[float, float]
    start_control: tuple[float, float]
    end_control: tuple[float, float]
    end: tuple[float, float]
    child_side: int
    parent_side: int
    waypoints: tuple[tuple[float, float], ...] = ()
    svg_path: str = ''
    merge_zones: tuple = ()


def route_endpoint_keys(route: RelationshipRoute):
    return ((route.relationship.child,route.relationship.column,route.child_side),
            (route.relationship.parent,route.relationship.parent_column,route.parent_side))


def card_size(table: Table) -> tuple[float, float]:
    """Estimate monospace card geometry without requiring installed fonts."""
    longest = max([len(table.name)] + [len(a) for a in table.annotations] + [len(column.name) + len(column.type) + 6
                                       for column in table.columns])
    return max(180, 38 + longest * 7), CARD_HEADER_HEIGHT + (len(table.columns) + len(table.annotations)) * CARD_ROW_HEIGHT


def rectangle_gap(first: Rect, second: Rect) -> float:
    horizontal = max(first.x - (second.x + second.width), second.x - (first.x + first.width), 0)
    vertical = max(first.y - (second.y + second.height), second.y - (first.y + first.height), 0)
    return math.hypot(horizontal, vertical)


def overlaps(first: Rect, second: Rect) -> bool:
    return (first.x < second.x + second.width and first.x + first.width > second.x and
            first.y < second.y + second.height and first.y + first.height > second.y)


def violates_card_gap(first: Rect, second: Rect) -> bool:
    return overlaps(first, second) or rectangle_gap(first, second) < MIN_CARD_GAP


def relationships(tables: list[Table]) -> list[Relationship]:
    known = {table.name for table in tables}
    return [Relationship(table.name, column.name, parent, parent_column, column.nullable)
            for table in tables for column in table.columns for parent, parent_column in column_references(column)
            if parent in known]


def routed_relationships(tables: list[Table]) -> list[Relationship]:
    """Return only edges between cards; self-FKs are rendered as local loops."""
    return [relationship for relationship in relationships(tables)
            if relationship.child != relationship.parent]


def relationship_route(relationship: Relationship, positioned: dict[str, PositionedTable],
                       child_side: int, parent_side: int) -> RelationshipRoute:
    """Attach a relationship to its child FK row and referenced parent-key row."""
    child = positioned[relationship.child]
    parent = positioned[relationship.parent]
    child_index = next(index for index, column in enumerate(child.table.columns)
                       if column.name == relationship.column)
    parent_index = next((index for index, column in enumerate(parent.table.columns)
                         if column.name == relationship.parent_column), 0)
    child_y = child.rect.y + CARD_HEADER_HEIGHT + child_index * CARD_ROW_HEIGHT + CARD_ROW_HEIGHT / 2
    parent_y = parent.rect.y + CARD_HEADER_HEIGHT + parent_index * CARD_ROW_HEIGHT + CARD_ROW_HEIGHT / 2
    start = (child.rect.x + (child.rect.width if child_side > 0 else 0), child_y)
    end = (parent.rect.x + (parent.rect.width if parent_side > 0 else 0), parent_y)
    vertically_aligned = not (child.rect.x + child.rect.width <= parent.rect.x or
                              parent.rect.x + parent.rect.width <= child.rect.x)
    if vertically_aligned:
        start_control = (start[0] + child_side * VERTICAL_CONNECTOR_CONTROL_OFFSET, start[1])
        end_control = (end[0] + parent_side * VERTICAL_CONNECTOR_CONTROL_OFFSET, end[1])
    else:
        midpoint = (start[0] + end[0]) / 2
        start_control = (start[0] + math.copysign(max(CONNECTOR_CONTROL_OFFSET, abs(midpoint - start[0]) * .4), midpoint - start[0]), start[1])
        end_control = (end[0] + math.copysign(max(CONNECTOR_CONTROL_OFFSET, abs(midpoint - end[0]) * .4), midpoint - end[0]), end[1])
    return RelationshipRoute(relationship, start, start_control, end_control, end, child_side, parent_side)


def legacy_relationship_routes(positioned: list[PositionedTable]) -> list[RelationshipRoute]:
    by_name = {item.table.name: item for item in positioned}
    routes = []
    for relationship in sorted(routed_relationships([item.table for item in positioned]),
                               key=lambda item: (item.parent, item.child, item.column)):
        child_rect = by_name[relationship.child].rect
        parent_rect = by_name[relationship.parent].rect
        if child_rect.x + child_rect.width <= parent_rect.x:
            sides = [(1, -1)]
        elif parent_rect.x + parent_rect.width <= child_rect.x:
            sides = [(-1, 1)]
        else:
            sides = [(child_side, parent_side) for child_side in (-1, 1) for parent_side in (-1, 1)]
        candidates = [relationship_route(relationship, by_name, child_side, parent_side)
                      for child_side, parent_side in sides]
        def cost(route: RelationshipRoute) -> tuple[int, int, float]:
            blocked = sum(route_crosses_rect(route, item.rect) for item in positioned
                          if item.table.name not in {relationship.child, relationship.parent})
            crossings = sum(routes_intersect(route, selected)
                            for selected in routes
                            if not ({relationship.child, relationship.parent} &
                                    {selected.relationship.child, selected.relationship.parent}))
            force = abs(route.start_control[0] - route.start[0]) + abs(route.end_control[0] - route.end[0])
            return blocked, crossings, force
        routes.append(min(candidates, key=cost))
    return routes


def self_relationship_routes(positioned: list[PositionedTable]) -> list[RelationshipRoute]:
    """Render a self-FK as a compact loop on the right side of its own card."""
    by_name={item.table.name:item for item in positioned}
    routes=[]
    for index,relationship in enumerate(sorted((relationship for relationship in relationships(
            [item.table for item in positioned]) if relationship.child == relationship.parent),
            key=lambda rel:(rel.child,rel.column,rel.parent_column))):
        item=by_name[relationship.child]
        child_row=next(row for row,column in enumerate(item.table.columns) if column.name == relationship.column)
        parent_row=next((row for row,column in enumerate(item.table.columns)
                         if column.name == relationship.parent_column),0)
        start=(item.rect.x+item.rect.width,item.rect.y+CARD_HEADER_HEIGHT+(child_row+.5)*CARD_ROW_HEIGHT)
        end=(item.rect.x+item.rect.width,item.rect.y+CARD_HEADER_HEIGHT+(parent_row+.5)*CARD_ROW_HEIGHT)
        loop_x=item.rect.x+item.rect.width+48+index*18
        points=(start,(loop_x,start[1]),(loop_x,end[1]),end)
        routes.append(RelationshipRoute(relationship,start,points[1],points[-2],end,1,1,points,
                                       svg_path=rounded_orthogonal_path(points,{})))
    return routes


def relationship_routes(positioned: list[PositionedTable], routing_passes: int = 2) -> list[RelationshipRoute]:
    if not routing_passes:
        routes=legacy_relationship_routes(positioned)
        routes.extend(self_relationship_routes(positioned))
        return routes

    def factory(rel, points, child_side, parent_side):
        return RelationshipRoute(rel,points[0],points[1],points[-2],points[-1],child_side,parent_side,points)

    def evaluate(routes):
        score=score_layout(positioned,routes)
        return score.table_intersections,score.line_intersections,score.total

    routes=route_all(positioned,routed_relationships([item.table for item in positioned]),routing_passes,factory,evaluate)
    zones=tuple(merge_junctions(positioned,{r.relationship:(r.waypoints,r.child_side,r.parent_side) for r in routes}))
    radii=shared_corner_radii({r.relationship:(r.waypoints,r.child_side,r.parent_side) for r in routes},positioned,zones)
    endpoints=Counter(key for route in routes for key in route_endpoint_keys(route))
    result=[]
    for route in routes:
        path,geometry=smooth_terminal_path(route.waypoints,route.child_side,route.parent_side,
                                           positioned,route.relationship.child,route.relationship.parent,
                                           endpoints[(route.relationship.child,route.relationship.column,route.child_side)]>1,
                                           endpoints[(route.relationship.parent,route.relationship.parent_column,route.parent_side)]>1,
                                           [(key,rect) for key,rect in zones if key not in endpoint_keys(route.relationship)],
                                           [(key,rect) for key,rect in zones if key in endpoint_keys(route.relationship)],radii)
        result.append(replace(route,waypoints=geometry,svg_path=path,merge_zones=zones))
    result.extend(self_relationship_routes(positioned))
    return result


def orientation(first: tuple[float, float], second: tuple[float, float], third: tuple[float, float]) -> float:
    return ((second[0] - first[0]) * (third[1] - first[1]) -
            (second[1] - first[1]) * (third[0] - first[0]))


def segments_intersect(first_start: tuple[float, float], first_end: tuple[float, float],
                       second_start: tuple[float, float], second_end: tuple[float, float]) -> bool:
    """Strict segment crossing; shared endpoints do not count as an intersection."""
    return ((orientation(first_start, first_end, second_start) * orientation(first_start, first_end, second_end) < 0) and
            (orientation(second_start, second_end, first_start) * orientation(second_start, second_end, first_end) < 0))


def segment_crosses_rect(start: tuple[float, float], end: tuple[float, float], rect: Rect) -> bool:
    return hits_rect(start,end,rect)


def expanded_rect(rect: Rect, padding: float = LINE_BLOCK_CLEARANCE) -> Rect:
    """Reserve visual breathing room between a connector and an unrelated card."""
    return Rect(rect.x - padding, rect.y - padding, rect.width + 2 * padding, rect.height + 2 * padding)


def route_segments(route: RelationshipRoute) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Approximate the rendered cubic Bézier with four collision segments."""
    if route.waypoints:
        return list(zip(route.waypoints,route.waypoints[1:]))
    points = []
    for index in range(5):
        t = index / 4
        inverse = 1 - t
        points.append((inverse ** 3 * route.start[0] + 3 * inverse ** 2 * t * route.start_control[0] +
                       3 * inverse * t ** 2 * route.end_control[0] + t ** 3 * route.end[0],
                       inverse ** 3 * route.start[1] + 3 * inverse ** 2 * t * route.start_control[1] +
                       3 * inverse * t ** 2 * route.end_control[1] + t ** 3 * route.end[1]))
    return list(zip(points, points[1:]))


def route_crosses_rect(route: RelationshipRoute, rect: Rect) -> bool:
    clearance_rect = expanded_rect(rect)
    return any(segment_crosses_rect(start, end, clearance_rect) for start, end in route_segments(route))


def routes_intersect(first: RelationshipRoute, second: RelationshipRoute) -> bool:
    return any(segments_intersect(start, end, other_start, other_end)
               for start, end in route_segments(first)
               for other_start, other_end in route_segments(second))


def score_layout(positioned: list[PositionedTable], routes: list[RelationshipRoute] | None = None) -> LayoutScore:
    routes = relationship_routes(positioned) if routes is None else routes
    card_hits = sum(route_crosses_rect(route, item.rect)
                    for route in routes for item in positioned
                    if item.table.name not in {route.relationship.child, route.relationship.parent})
    line_hits = sum(routes_intersect(first, second)
                    for index, first in enumerate(routes) for second in routes[index + 1:]
                    if not ({first.relationship.child, first.relationship.parent} &
                            {second.relationship.child, second.relationship.parent}))
    straight_connections = sum(abs(route.start[1] - route.end[1]) < .001 for route in routes)
    gaps = [rectangle_gap(first.rect, second.rect) for index, first in enumerate(positioned)
            for second in positioned[index + 1:]]
    return LayoutScore(card_hits, line_hits, straight_connections, min(gaps, default=0),
                       sum(gaps) / len(gaps) if gaps else 0)


def preoptimized_order(tables: list[Table], seed: str | None = None) -> list[Table]:
    """Seed layout from leaf tables, then grow through already placed neighbours."""
    by_name = {table.name: table for table in tables}
    neighbours = {table.name: set() for table in tables}
    for relationship in routed_relationships(tables):
        neighbours[relationship.child].add(relationship.parent)
        neighbours[relationship.parent].add(relationship.child)
    leaves = sorted((name for name, linked in neighbours.items() if len(linked) == 1))
    if seed is not None:
        placed = [seed]
        placed.extend(sorted(neighbours[seed])[:1])
        placed.extend(name for name in leaves if name not in placed)
    else:
        placed = list(leaves)
    remaining = set(by_name) - set(placed)
    while remaining:
        next_name = min(remaining, key=lambda name: (
            -len(neighbours[name] & set(placed)), len(neighbours[name]), name))
        placed.append(next_name)
        remaining.remove(next_name)
    return [by_name[name] for name in placed]


def layout_variant(tables: list[Table], seed: str | None = None,
                   fixed_positions: dict[str, tuple[float, float]] | None = None) -> list[PositionedTable]:
    """Deterministic grid start plus bounded local improvement for the ERD score."""
    # Routing is an exact finalisation step. Candidate placement uses the stable
    # compact geometry; invoking the obstacle router per proposal is quadratic.
    def candidate_score(items: list[PositionedTable]) -> LayoutScore:
        return score_layout(items,legacy_relationship_routes(items))

    degrees = {table.name: 0 for table in tables}
    for relationship in routed_relationships(tables):
        degrees[relationship.child] += 1
        degrees[relationship.parent] += 1
    ordered = preoptimized_order(tables, seed)
    widths = [card_size(table)[0] for table in ordered]
    heights = [card_size(table)[1] for table in ordered]
    pitch_x = max(widths, default=180) + CARD_GUTTER
    pitch_y = max(heights, default=60) + CARD_GUTTER
    columns = max(3, math.ceil(math.sqrt(len(ordered))) + 2)
    fixed_positions = fixed_positions or {}
    positioned = [PositionedTable(table, Rect(*fixed_positions.get(table.name, ((index % columns) * pitch_x,
                                                                                 (index // columns) * pitch_y)),
                                               *card_size(table)))
                  for index, table in enumerate(ordered)]
    directions = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1))
    for step in (pitch_x / 2, pitch_y / 2, min(pitch_x, pitch_y) / 4):
        for index, item in enumerate(positioned):
            if index < 2 or item.table.name in fixed_positions:
                continue
            current_layout_score = candidate_score(positioned)
            current_score = current_layout_score.total
            best = item
            for dx, dy in directions:
                candidate = PositionedTable(item.table, Rect(item.rect.x + dx * step,
                                                               item.rect.y + dy * step,
                                                               item.rect.width, item.rect.height))
                trial = positioned[:]
                trial[index] = candidate
                if any(violates_card_gap(candidate.rect, other.rect) for other_index, other in enumerate(trial)
                       if other_index != index):
                    continue
                candidate_layout_score = candidate_score(trial)
                if (current_layout_score.table_intersections == 0 and
                        candidate_layout_score.table_intersections > 0):
                    continue
                candidate_total = candidate_layout_score.total
                if candidate_total < current_score:
                    current_score, best = candidate_total, candidate
            positioned[index] = best
    # A relationship through an unrelated table makes the diagram unreadable. Give those
    # high-cost cases extra deterministic escape attempts after compacting the layout.
    for _ in range(len(positioned) * 2):
        baseline = candidate_score(positioned)
        improved = False
        for index, item in enumerate(positioned):
            if index < 2 or item.table.name in fixed_positions:
                continue
            for dx, dy in directions:
                candidate = PositionedTable(item.table, Rect(item.rect.x + dx * pitch_x / 2,
                                                               item.rect.y + dy * pitch_y / 2,
                                                               item.rect.width, item.rect.height))
                trial = positioned[:]
                trial[index] = candidate
                if any(violates_card_gap(candidate.rect, other.rect) for other_index, other in enumerate(trial)
                       if other_index != index):
                    continue
                trial_score = candidate_score(trial)
                if ((trial_score.table_intersections, trial_score.total) <
                        (baseline.table_intersections, baseline.total)):
                    positioned = trial
                    improved = True
                    break
            if improved:
                break
        if not improved:
            break
    return positioned


def layout_tables(tables: list[Table], fixed_positions: dict[str, tuple[float, float]] | None = None,
                  options: LayoutOptions | None = None) -> list[PositionedTable]:
    """Pick the best deterministic leaf-seeded layout while retaining a stable output."""
    if len(tables) > 24:
        ordered = preoptimized_order(tables)
        gutter=max(CARD_GUTTER,TRANSPORT_GAP+24)
        pitch_x = max(card_size(t)[0] for t in ordered) + gutter
        pitch_y = max(card_size(t)[1] for t in ordered) + gutter
        columns = math.ceil(math.sqrt(len(ordered)))
        initial = [PositionedTable(t, Rect(*(fixed_positions or {}).get(t.name,
                    ((i % columns) * pitch_x, (i // columns) * pitch_y)), *card_size(t)))
                for i, t in enumerate(ordered)]
        if any(violates_card_gap(a.rect,b.rect) for i,a in enumerate(initial) for b in initial[i+1:]):
            raise ValueError('Fixed layout positions overlap cards or violate the minimum gap')
        return optimize_grid(initial,routed_relationships(tables),options or LayoutOptions(),fixed_positions or {})
    degrees = {table.name: 0 for table in tables}
    for relationship in routed_relationships(tables):
        degrees[relationship.child] += 1
        degrees[relationship.parent] += 1
    seeds = sorted(name for name, degree in degrees.items() if degree == 1) or [None]
    variants = [layout_variant(tables, seed, fixed_positions) for seed in seeds]
    return min(variants, key=lambda variant: (score_layout(variant).total,
                                               tuple(item.table.name for item in variant)))


def svg_escape(value: str) -> str:
    return html.escape(value, quote=True)


def render_svg(tables: list[Table], fixed_positions: dict[str, tuple[float, float]] | None = None,
               options: LayoutOptions | None = None, stats: dict | None = None) -> str:
    if not tables:
        raise ValueError("ERD не содержит таблиц для SVG-рендера")
    options=options or LayoutOptions()
    positioned = layout_tables(tables, fixed_positions, options)
    routes=relationship_routes(positioned,options.routing_passes)
    if stats is not None:
        stats.update(asdict(score_layout(positioned,routes)))
        polylines=[(set(route_endpoint_keys(route)),trim_ports(route.waypoints)) for route in routes if route.waypoints]
        overlaps=[]
        unrelated=[]
        for i,(keys,first) in enumerate(polylines):
            for other_keys,second in polylines[i+1:]:
                length=overlap_length(first,second)
                overlaps.append(length)
                if not keys & other_keys:
                    unrelated.append(length)
        stats.update(overlapping_pairs=sum(length>0 for length in overlaps),
                     shared_length=round(sum(overlaps),2),
                     unrelated_overlapping_pairs=sum(length>0 for length in unrelated),
                     unrelated_shared_length=round(sum(unrelated),2))
        zones=routes[0].merge_zones if routes else ()
        stats['merge_crossing_routes']=len(junction_conflicts(
            {r.relationship:(r.waypoints,r.child_side,r.parent_side) for r in routes},zones))
    by_name = {item.table.name: item for item in positioned}
    min_x = min(item.rect.x for item in positioned) - LAYOUT_PADDING
    min_y = min(item.rect.y for item in positioned) - LAYOUT_PADDING
    max_x = max(item.rect.x + item.rect.width for item in positioned) + LAYOUT_PADDING
    max_y = max(item.rect.y + item.rect.height for item in positioned) + LAYOUT_PADDING
    points=[point for route in routes for point in (route.waypoints or
            (route.start,route.start_control,route.end_control,route.end))]
    if points:
        min_x=min(min_x,min(p[0] for p in points)-LAYOUT_PADDING)
        min_y=min(min_y,min(p[1] for p in points)-LAYOUT_PADDING)
        max_x=max(max_x,max(p[0] for p in points)+LAYOUT_PADDING)
        max_y=max(max_y,max(p[1] for p in points)+LAYOUT_PADDING)
    lines = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="%g %g %g %g" font-family="ui-sans-serif, system-ui, sans-serif">' %
             (max_x - min_x, max_y - min_y, min_x, min_y, max_x - min_x, max_y - min_y),
             '<defs><marker id="many-right" markerWidth="12" markerHeight="12" refX="8" refY="6" orient="0" overflow="visible"><path d="M0 6 L8 1 M0 6 L8 6 M0 6 L8 11" fill="none" stroke="#5d6b7d" stroke-width="1.5"/></marker><marker id="many-left" markerWidth="12" markerHeight="12" refX="0" refY="6" orient="0" overflow="visible"><path d="M8 6 L0 1 M8 6 L0 6 M8 6 L0 11" fill="none" stroke="#5d6b7d" stroke-width="1.5"/></marker><marker id="zero-many-right" markerWidth="18" markerHeight="12" refX="10" refY="6" orient="0" overflow="visible"><circle cx="5" cy="6" r="2.5" fill="#0e1116" stroke="#5d6b7d" stroke-width="1.5"/><path d="M8 6 L15 1 M8 6 L15 6 M8 6 L15 11" fill="none" stroke="#5d6b7d" stroke-width="1.5"/></marker><marker id="zero-many-left" markerWidth="18" markerHeight="12" refX="0" refY="6" orient="0" overflow="visible"><circle cx="10" cy="6" r="2.5" fill="#0e1116" stroke="#5d6b7d" stroke-width="1.5"/><path d="M7 6 L0 1 M7 6 L0 6 M7 6 L0 11" fill="none" stroke="#5d6b7d" stroke-width="1.5"/></marker></defs>',
             ]
    for route in routes:
        relationship = route.relationship
        marker = ("zero-many" if relationship.nullable else "many") + ("-left" if route.child_side > 0 else "-right")
        if route.svg_path:
            path=route.svg_path
        elif route.waypoints:
            path='M %g %g' % route.waypoints[0] + ''.join(' L %g %g' % point for point in route.waypoints[1:])
        else:
            path='M %g %g C %g %g, %g %g, %g %g' % (route.start[0],route.start[1],route.start_control[0],
                 route.start_control[1],route.end_control[0],route.end_control[1],route.end[0],route.end[1])
        title=f'{relationship.child}.{relationship.column} → {relationship.parent}.{relationship.parent_column}'
        lines.append('<path class="relationship" d="%s" fill="none" stroke="#5d6b7d" stroke-width="1.5" marker-start="url(#%s)"><title>%s</title></path>' %
                     (path,marker,svg_escape(title)))
    for item in positioned:
        table, rect = item.table, item.rect
        lines.append('<g transform="translate(%g %g)"><rect width="%g" height="%g" rx="10" fill="#1b212b" stroke="#2b333f"/>' %
                     (rect.x, rect.y, rect.width, rect.height))
        lines.append('<path d="M0 %d V10 a10 10 0 0 1 10 -10 H%g a10 10 0 0 1 10 10 V%d Z" fill="#222c3a"/>' %
                     (CARD_HEADER_HEIGHT, rect.width - 10, CARD_HEADER_HEIGHT))
        lines.append('<text x="12" y="17" dominant-baseline="middle" font-weight="600" font-size="14" fill="#e8edf4">%s</text>' % svg_escape(table.name))
        for index, column in enumerate(table.columns):
            y = CARD_HEADER_HEIGHT + index * CARD_ROW_HEIGHT
            if index % 2:
                lines.append('<rect x="1" y="%d" width="%g" height="%d" fill="#1e2530"/>' %
                             (y, rect.width - 2, CARD_ROW_HEIGHT))
            marker = "PK" if column.primary else "FK" if column.reference else ""
            color = "#f5c451" if column.primary else "#5aa7ff"
            if marker:
                lines.append('<text x="10" y="%g" dominant-baseline="middle" font-size="9" font-weight="700" fill="%s">%s</text>' %
                             (y + 13, color, marker))
            for x, label, color, enabled in ((25, "UQ", "#b48cff", column.unique),
                                              (39, "IX", "#7eb68a", column.indexed),
                                              (53, "TRG", "#d98cff", column.trigger)):
                if enabled:
                    lines.append('<text x="%g" y="%g" dominant-baseline="middle" font-size="8" font-weight="700" fill="%s">%s</text>' %
                                 (x, y + 13, color, label))
            lines.append('<text x="70" y="%g" dominant-baseline="middle" font-size="13" font-family="ui-monospace, Menlo, monospace" fill="#c4ccd6">%s</text>' %
                         (y + 13, svg_escape(column.name)))
            lines.append('<text x="%g" y="%g" dominant-baseline="middle" text-anchor="end" font-size="12" font-family="ui-monospace, Menlo, monospace" fill="#6f7b8a">%s</text>' %
                         (rect.width - 12, y + 13, svg_escape(column.type)))
        for offset, annotation in enumerate(table.annotations):
            y = CARD_HEADER_HEIGHT + (len(table.columns) + offset) * CARD_ROW_HEIGHT
            kind, name = annotation.split(" ", 1)
            color = "#d98cff" if kind == "TRG" else "#b48cff"
            lines.append('<text x="25" y="%g" dominant-baseline="middle" font-size="8" font-weight="700" fill="%s">%s</text>' %
                         (y + 13, color, kind))
            lines.append('<text x="50" y="%g" dominant-baseline="middle" font-size="12" font-family="ui-monospace, Menlo, monospace" fill="#c4ccd6">%s</text>' %
                         (y + 13, svg_escape(name)))
        lines.append('</g>')
    return "\n".join(lines + ['</svg>', ''])


# ─────────────────────────── проверка DDL ───────────────────────────

def verify(sql_path: Path, dry_run: bool) -> int:
    """Прогоняет db.sql на чистой PostgreSQL в docker: черновик схемы должен хотя бы выполняться."""
    command = ["docker", "run", "-d", "--rm", "--name", PG_CONTAINER,
               "-e", "POSTGRES_PASSWORD=check",
               "-v", "%s:/sql:ro" % sql_path.parent, POSTGRES_IMAGE]
    if dry_run:
        print(" ".join(command))
        return 0
    if which("docker") is None:
        print("Нет docker — проверить DDL нечем.", file=sys.stderr)
        return 1
    try:
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL)

        # контейнер поднимается в два приёма: временный сервер для initdb, затем настоящий.
        # ждём двух успешных ответов подряд — иначе psql попадает на временный и теряет связь
        def probe() -> bool:
            return subprocess.run(
                ["docker", "exec", PG_CONTAINER, "psql", "-U", "postgres", "-At", "-c", "select 1"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0

        for _ in range(90):
            if probe():
                time.sleep(3)
                if probe():
                    break
            time.sleep(1)
        else:
            print("PostgreSQL не поднялась за 90 с", file=sys.stderr)
            return 1

        applied = subprocess.run(
            ["docker", "exec", PG_CONTAINER, "psql", "-U", "postgres", "-v", "ON_ERROR_STOP=1",
             "-q", "-f", "/sql/%s" % sql_path.name], capture_output=True, text=True)
        if applied.returncode != 0:
            print("DDL не выполнился:", file=sys.stderr)
            print(applied.stderr.strip()[:800], file=sys.stderr)
            return 1
        counts = subprocess.run(
            ["docker", "exec", PG_CONTAINER, "psql", "-U", "postgres", "-At", "-c",
             "select (select count(*) from information_schema.tables where table_schema='public') "
             "|| ' таблиц, ' || (select count(*) from information_schema.table_constraints "
             "where constraint_type='FOREIGN KEY') || ' внешних ключей'"],
            capture_output=True, text=True)
        print("DDL выполняется на чистой PostgreSQL: %s" % counts.stdout.strip())
        return 0
    finally:
        subprocess.run(["docker", "rm", "-f", PG_CONTAINER],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ─────────────────────────── CLI ───────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DDL, Mermaid и SVG ERD из Liquibase-чанжлога")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2]), help="корень DocsApp")
    parser.add_argument("--check", action="store_true",
                        help="не писать файлы, а проверить их соответствие чанжлогу")
    parser.add_argument("--verify", action="store_true",
                        help="прогнать db.sql на чистой PostgreSQL в docker")
    parser.add_argument("--mermaid", action="store_true", help="только напечатать erDiagram")
    parser.add_argument("--render", action="store_true",
                        help="совместимый алиас локальной генерации SVG")
    parser.add_argument("--print-command", action="store_true",
                        help="показать команду проверки, ничего не запуская")
    parser.add_argument('--layout-steps',type=int,help='число предложений перестановки таблиц большой схемы')
    parser.add_argument('--routing-passes',type=int,help='число проходов обходящей блоки разводки; 0 — старые кривые')
    parser.add_argument('--layout-seed',type=int,help='seed воспроизводимой оптимизации')
    parser.add_argument('--layout-stats',action='store_true',help='показать число пересечений линий с блоками и линиями')
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    sql, files, warnings = collect_sql(root)
    for warning in dict.fromkeys(warnings):
        print("⚠ %s" % warning, file=sys.stderr)

    tables = parse_ddl(sql)
    fixed_positions = load_fixed_positions(root, tables)
    options=load_layout_options(root,args.layout_steps,args.routing_passes,args.layout_seed)

    if args.mermaid:
        print(render_mermaid(tables))
        return 0

    stats={} if args.layout_stats else None
    artifacts = {
        root / DB_SQL: build_sql(root, sql, files),
        root / ERD_MD: build_erd(tables),
        root / ERD_SVG: render_svg(tables, fixed_positions,options,stats),
    }
    if stats is not None:
        print('ERD layout: '+json.dumps({'steps':options.steps,'routing_passes':options.routing_passes,
              'seed':options.seed,**stats},ensure_ascii=False,sort_keys=True))

    relations = sum(len(table.foreign_keys) for table in tables)

    if args.check:
        stale = [path for path, content in artifacts.items()
                 if not path.is_file() or path.read_text(encoding="utf-8") != content]
        if stale:
            print("Расходится с чанжлогом: %s" % ", ".join(
                path.relative_to(root).as_posix() for path in stale))
            print("Пересоберите: make db-schema")
            return 1
        print("db.sql, erd.md и schema.svg соответствуют чанжлогу: %d таблиц, %d %s" % (
            len(tables), relations, "внешний ключ" if relations == 1 else "внешних ключей"))
        return 0

    for path, content in artifacts.items():
        rel = path.relative_to(root).as_posix()
        current = path.read_text(encoding="utf-8") if path.is_file() else None
        if current == content:
            print("%s уже актуален" % rel)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print("%s пересобран из чанжлога" % rel)

    if args.verify:
        return verify(root / DB_SQL, dry_run=args.print_command)
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    raise SystemExit(main())
