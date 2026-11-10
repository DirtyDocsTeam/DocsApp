#!/usr/bin/env python3
"""Связи C4-контекста: направления берутся из наконечников стрелок.

Читает `documentation/design/context.drawio` и обновляет (или проверяет) таблицу связей внутри
`documentation/design/design.md` между маркерами `c4-relations`.

Зачем: направление связи в тексте легко перепутать — особенно когда подпись ребра
(`gRPC [Token validate]`) не говорит, кто кого вызывает. В диаграмме направление задано
наконечником: `endArrow` рисует его у `target`, `startArrow` — у `source`. Скрипт делает таблицу
производной от диаграммы, поэтому люди (видят стрелки) и агенты (читают текст) получают одно и то же.

Использование:
  python3 .github/scripts/c4_relations.py --write   # перегенерировать таблицу в design.md
  python3 .github/scripts/c4_relations.py --check   # проверить соответствие (код 1 при расхождении)
  python3 .github/scripts/c4_relations.py --print   # только показать таблицу

Зависимости — стандартная библиотека Python.
"""
from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

DRAWIO = "documentation/design/context.drawio"
DESIGN = "documentation/design/design.md"

BEGIN = ("<!-- c4-relations:begin — таблица генерируется `.github/scripts/c4_relations.py` "
         "из `context.drawio`; правки внутри блока перезапишутся -->")
END = "<!-- c4-relations:end -->"
BEGIN_RE = re.compile(r"<!--\s*c4-relations:begin[^>]*?-->")
END_RE = re.compile(r"<!--\s*c4-relations:end[^>]*?-->")

ARROW_LABEL = {
    "target": "у «куда»",
    "source": "у «откуда»",
    "none": "нет",
}


@dataclass
class Node:
    nid: str
    name: str
    kind: str = ""
    technology: str = ""
    position: tuple[float, float] = (0.0, 0.0)


@dataclass
class Edge:
    eid: str
    source: str
    target: str
    label: str
    arrowhead: str            # target | source | none

    @property
    def direction(self) -> tuple[str, str]:
        """(откуда, куда) — по наконечнику; без наконечника порядок как в файле."""
        return (self.target, self.source) if self.arrowhead == "source" \
            else (self.source, self.target)


def clean(value: str) -> str:
    text = (value or "").replace("&gt;", ">").replace("&lt;", "<").replace("&amp;", "&")
    text = re.sub(r"<br\s*/?>", " ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"%c4\w+%", "", text)
    return re.sub(r"\s+", " ", text).strip(" /").strip()


def arrowhead_of(style: str) -> str:
    """Где нарисован наконечник: `endArrow` по умолчанию `classic`, `startArrow` — нет."""
    start = re.search(r"startArrow=([^;]+)", style or "")
    end = re.search(r"endArrow=([^;]+)", style or "")
    start = (start.group(1) if start else "none").strip()
    end = (end.group(1) if end else "classic").strip()
    if end != "none":
        return "target"
    if start != "none":
        return "source"
    return "none"


def positions(root) -> dict[str, tuple[float, float]]:
    """Абсолютные координаты узлов: у детей групп координаты относительные, суммируем по цепочке."""
    raw: dict[str, tuple[str, float, float]] = {}
    for element in root.iter():
        if element.tag not in {"object", "UserObject", "mxCell"}:
            continue
        cid = element.get("id")
        if not cid:
            continue
        cell = element.find("mxCell") if element.tag != "mxCell" else element
        if cell is None:
            continue
        geo = cell.find("mxGeometry")
        try:
            x = float(geo.get("x")) if geo is not None and geo.get("x") is not None else 0.0
            y = float(geo.get("y")) if geo is not None and geo.get("y") is not None else 0.0
        except ValueError:
            x = y = 0.0
        raw[cid] = (cell.get("parent") or "", x, y)

    absolute: dict[str, tuple[float, float]] = {}
    for cid in raw:
        x = y = 0.0
        cursor, depth = cid, 0
        while cursor in raw and depth < 20:
            parent, px, py = raw[cursor]
            x += px
            y += py
            cursor = parent
            depth += 1
        absolute[cid] = (y, x)
    return absolute


def load(drawio: Path) -> tuple[dict[str, Node], list[Edge], list[str]]:
    """Узлы C4 хранятся как `<object c4Name=…>`, рёбра и подписи — как `<mxCell>`."""
    warnings: list[str] = []
    root = ET.fromstring(drawio.read_text(encoding="utf-8"))

    geometry = positions(root)
    nodes: dict[str, Node] = {}
    for element in root.iter():
        if element.tag not in {"object", "UserObject", "mxCell"}:
            continue
        nid = element.get("id")
        if not nid or element.get("edge") == "1":
            continue
        cell = element.find("mxCell") if element.tag != "mxCell" else element
        if cell is None or cell.get("vertex") != "1":
            continue
        if "edgeLabel" in (cell.get("style") or ""):
            continue
        name = clean(element.get("c4Name") or element.get("label") or "")
        if not name:
            continue
        nodes[nid] = Node(nid=nid, name=name, kind=clean(element.get("c4Type") or ""),
                          technology=clean(element.get("c4Technology") or ""))
        nodes[nid].position = geometry.get(nid, (0.0, 0.0))

    labels: dict[str, list[str]] = {}
    edges: list[Edge] = []
    for cell in root.iter("mxCell"):
        if cell.get("edge") == "1":
            edges.append(Edge(eid=cell.get("id") or "", source=cell.get("source") or "",
                              target=cell.get("target") or "",
                              label=clean(cell.get("value")),
                              arrowhead=arrowhead_of(cell.get("style") or "")))
        elif "edgeLabel" in (cell.get("style") or ""):
            text = clean(cell.get("value"))
            if text:
                labels.setdefault(cell.get("parent") or "", []).append(text)

    for edge in edges:
        if not edge.label:
            edge.label = " ".join(labels.get(edge.eid, []))
        for endpoint in (edge.source, edge.target):
            if endpoint not in nodes:
                warnings.append("ребро `…%s` ссылается на узел `%s`, которого нет в диаграмме"
                                % (edge.eid[-3:], endpoint[-6:]))
    idle = [node.name for node in nodes.values()
            if not any(node.nid in (edge.source, edge.target) for edge in edges)]
    if idle:
        print("ℹ без собственных связей (участники границы или пул): %s" % ", ".join(sorted(idle)),
              file=sys.stderr)
    return nodes, edges, warnings


def build(nodes: dict[str, Node], edges: list[Edge]) -> list[tuple[str, str, str, str, str]]:
    """Строки таблицы: одинаковые связи схлопываются, id рёбер перечисляются через запятую."""
    def place(nid: str) -> tuple[float, float]:
        return nodes[nid].position if nid in nodes else (1e9, 1e9)

    ordered = sorted(edges, key=lambda edge: (place(edge.direction[0]), place(edge.direction[1])))

    grouped: dict[tuple[str, str, str, str], list[str]] = {}
    for edge in ordered:
        origin_id, dest_id = edge.direction
        origin = nodes[origin_id].name if origin_id in nodes else "узел …%s" % origin_id[-3:]
        dest = nodes[dest_id].name if dest_id in nodes else "узел …%s" % dest_id[-3:]
        key = (origin, dest, edge.label or "—", ARROW_LABEL[edge.arrowhead])
        grouped.setdefault(key, []).append("…%s" % edge.eid[-3:])
    return [(origin, dest, label, arrow, ", ".join(ids))
            for (origin, dest, label, arrow), ids in grouped.items()]


def render(rows: list[tuple[str, str, str, str, str]], edges_count: int,
           warnings: list[str]) -> str:
    def pair(origin: str, dest: str, arrow: str) -> str:
        return "%s %s %s" % (origin, "—" if arrow == ARROW_LABEL["none"] else "→", dest)

    lines = ["", "", BEGIN, "",
             "Кто с кем разговаривает — в порядке диаграммы, сверху вниз. `—` вместо стрелки значит, "
             "что на ребре нет наконечника (просто связь). Всего связей: %d." % edges_count,
             ""]
    for warning in warnings:
        lines += ["> ⚠ %s" % warning, ""]
    if warnings:
        lines.append("")

    lines += ["| Связь | Канал и данные |", "|---|---|"]
    for origin, dest, label, arrow, _ in rows:
        channel = "`%s`" % label if label != "—" else "—"
        if arrow == ARROW_LABEL["none"]:
            channel += " (линия без наконечника)"
        lines.append("| %s | %s |" % (pair(origin, dest, arrow), channel))

    lines += ["", "<details>", "<summary>Служебное: сверка с диаграммой</summary>", "",
              "Каждая строка выше соответствует ребру в [`context.drawio`](context.drawio). "
              "Колонка «наконечник» показывает, у какого конца он нарисован — по ней и вычислено "
              "направление; `id` позволяет найти ребро в файле.", "",
              "| Связь | Подпись в диаграмме | Наконечник | id ребра |", "|---|---|---|---|"]
    for origin, dest, label, arrow, ids in rows:
        lines.append("| %s | %s | %s | %s |" % (
            pair(origin, dest, arrow), "`%s`" % label if label != "—" else "—", arrow, ids))
    lines += ["", "</details>", "", END, ""]
    return "\n".join(lines)


def replace_block(markdown: str, block: str) -> str:
    begin, end = BEGIN_RE.search(markdown), END_RE.search(markdown)
    if not begin or not end or end.start() < begin.end():
        raise SystemExit(
            "В %s нет маркеров c4-relations. Добавьте их вокруг таблицы связей:\n%s\n…\n%s"
            % (DESIGN, BEGIN, END))
    return "%s\n%s" % (markdown[:begin.start()].rstrip("\n") + block,
                        markdown[end.end():].lstrip("\n"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Таблица связей C4 из context.drawio")
    parser.add_argument("--root", default=".", help="корень репозитория")
    parser.add_argument("--write", action="store_true", help="переписать блок в design.md")
    parser.add_argument("--check", action="store_true", help="проверить блок (код 1 при расхождении)")
    parser.add_argument("--print", dest="show", action="store_true", help="только напечатать таблицу")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    drawio, design = root / DRAWIO, root / DESIGN
    for path in (drawio, design):
        if not path.is_file():
            raise SystemExit("Не найден %s" % path)

    nodes, edges, warnings = load(drawio)
    rows = build(nodes, edges)
    block = render(rows, len(edges), warnings)
    for warning in warnings:
        print("⚠ %s" % warning, file=sys.stderr)

    if args.show:
        print(block)
        return 0

    markdown = design.read_text(encoding="utf-8")
    updated = replace_block(markdown, block)

    if args.write:
        if updated != markdown:
            design.write_text(updated, encoding="utf-8")
            print("Таблица связей обновлена в %s (%d строк)" % (DESIGN, len(rows)))
        else:
            print("Таблица связей уже актуальна (%d строк)" % len(rows))
        return 0

    if args.check:
        if updated != markdown:
            print("Таблица связей в %s расходится с %s." % (DESIGN, DRAWIO))
            print("Пересоберите: make c4-relations")
            return 1
        print("Таблица связей соответствует диаграмме (%d строк)" % len(rows))
        return 0

    print(block)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
