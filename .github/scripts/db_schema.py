#!/usr/bin/env python3
"""Схема БД из Liquibase-чанжлога: единый DDL и ERD на Mermaid.

Источник правды по схеме — чанжлог в `backend/api/src/main/resources/db/changelog/`.
Скрипт разворачивает master-файл (`include`, `includeAll`, `sqlFile`) и собирает из него два
производных артефакта:

  * `documentation/design/db.sql` — единый DDL для чтения и прогона в psql;
  * `documentation/design/erd.md` — ERD на Mermaid (`erDiagram`). Mermaid рендерят GitHub и вики,
    поэтому картинка не нужна: диаграмма остаётся текстом и диффится как код.

Использование:
  python3 .github/scripts/db_schema.py            # пересобрать db.sql и erd.md
  python3 .github/scripts/db_schema.py --check     # проверить, что артефакты соответствуют чанжлогу
  python3 .github/scripts/db_schema.py --verify    # прогнать DDL на чистой PostgreSQL в docker
  python3 .github/scripts/db_schema.py --mermaid   # только напечатать erDiagram

Зависимости — стандартная библиотека Python 3.11+. `--verify` дополнительно требует docker.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from shutil import which

from yaml_subset import YamlSubset

CHANGELOG_DIR = "backend/api/src/main/resources/db/changelog"
MASTER = CHANGELOG_DIR + "/db.changelog-master.yaml"
DB_SQL = "documentation/design/db.sql"
ERD_MD = "documentation/design/erd.md"

POSTGRES_IMAGE = "postgres:16-alpine"
PG_CONTAINER = "docsapp-dbcheck"

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

```mermaid
{diagram}
```

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


# ─────────────────────────── разбор DDL ───────────────────────────

COLUMN_KEYWORDS = ("not null", "null", "default", "primary key", "unique", "references",
                   "check", "generated", "constraint", "collate")

TABLE_RE = re.compile(r"create\s+table\s+(?:if\s+not\s+exists\s+)?([\w.]+)\s*\(", re.I)
REFERENCES_RE = re.compile(r"references\s+([\w.]+)\s*\(\s*(\w+)\s*\)", re.I)
COLUMN_PK_RE = re.compile(r"primary\s+key", re.I)
TABLE_PK_RE = re.compile(r"primary\s+key\s*\(([^)]*)\)", re.I)


@dataclass
class Column:
    name: str
    type: str
    nullable: bool = True
    primary: bool = False
    reference: tuple[str, str] | None = None   # (таблица, колонка)


@dataclass
class Table:
    name: str
    columns: list[Column] = field(default_factory=list)

    def column(self, name: str) -> Column | None:
        return next((column for column in self.columns if column.name == name), None)


def split_table_name(raw: str) -> str:
    return raw.split(".")[-1]


def parse_ddl(sql: str) -> list[Table]:
    """Достаёт из DDL таблицы, колонки, первичные и внешние ключи.

    Разбор намеренно простой: он читает вывод самого скрипта и Liquibase-чанжлог, а не
    произвольный SQL, поэтому ALTER TABLE и наследование типов не поддерживаются.
    """
    tables: list[Table] = []
    compact = re.sub(r"--[^\n]*", "", sql)
    position = 0
    while True:
        match = TABLE_RE.search(compact, position)
        if not match:
            break
        open_paren = match.end() - 1
        depth = 0
        end = open_paren
        for index in range(open_paren, len(compact)):
            if compact[index] == "(":
                depth += 1
            elif compact[index] == ")":
                depth -= 1
                if depth == 0:
                    end = index
                    break
        body = compact[open_paren + 1:end]
        position = end + 1

        table = Table(name=split_table_name(match.group(1)))
        table_keys: list[str] = []
        for raw_line in body.splitlines():
            line = raw_line.strip().rstrip(",").strip()
            if not line:
                continue
            lowered = line.lower()
            table_pk = TABLE_PK_RE.search(line)
            if table_pk and lowered.startswith(("primary key", "constraint", "unique")):
                table_keys.extend(part.strip().strip('"') for part in table_pk.group(1).split(","))
                continue
            if lowered.startswith(("primary key", "unique", "constraint", "check", "foreign key")):
                continue
            parts = line.split(None, 1)
            if len(parts) < 2:
                continue
            name, rest = parts[0].strip('"'), parts[1]
            # тип — всё до первого служебного слова (берём самое левое совпадение, иначе
            # `bigint GENERATED BY DEFAULT AS IDENTITY` разрежется по `default`)
            cut = len(rest)
            for keyword in COLUMN_KEYWORDS:
                found = re.search(r"\b%s\b" % keyword.replace(" ", r"\s+"), rest, re.I)
                if found:
                    cut = min(cut, found.start())
            type_text = rest[:cut]
            column = Column(name=name, type=re.sub(r"\s+", " ", type_text).strip(),
                            nullable="not null" not in lowered,
                            primary=bool(COLUMN_PK_RE.search(rest)))
            reference = REFERENCES_RE.search(rest)
            if reference:
                column.reference = (split_table_name(reference.group(1)), reference.group(2))
            table.columns.append(column)

        for key in table_keys:
            column = table.column(key)
            if column is not None:
                column.primary = True
        if table.columns:
            tables.append(table)
    tables.sort(key=lambda item: item.name)
    return tables


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
            if not column.reference:
                continue
            parent = column.reference[0]
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
            if not column.reference:
                continue
            found = True
            parent, parent_column = column.reference
            rows.append("| `%s` | `%s` | `%s` | `%s` | %s |" % (
                table.name, column.name, parent, parent_column,
                "нет" if column.nullable else "да"))
    return "\n".join(rows) if found else "_Внешних ключей нет._"


def build_erd(tables: list[Table]) -> str:
    return ERD_HEADER.format(changelog=CHANGELOG_DIR, diagram=render_mermaid(tables),
                             relations=render_relations(tables))


# ─────────────────────────── проверка DDL ───────────────────────────

def verify(sql_path: Path, dry_run: bool) -> int:
    """Прогоняет db.sql на чистой PostgreSQL в docker: черновик схемы должен хотя бы выполняться."""
    if which("docker") is None:
        print("Нет docker — проверить DDL нечем.", file=sys.stderr)
        return 1
    command = ["docker", "run", "-d", "--rm", "--name", PG_CONTAINER,
               "-e", "POSTGRES_PASSWORD=check",
               "-v", "%s:/sql:ro" % sql_path.parent, POSTGRES_IMAGE]
    if dry_run:
        print(" ".join(command))
        return 0
    subprocess.run(["docker", "rm", "-f", PG_CONTAINER],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
    parser = argparse.ArgumentParser(description="DDL и ERD (Mermaid) из Liquibase-чанжлога")
    parser.add_argument("--root", default=".", help="корень репозитория")
    parser.add_argument("--check", action="store_true",
                        help="не писать файлы, а проверить их соответствие чанжлогу")
    parser.add_argument("--verify", action="store_true",
                        help="прогнать db.sql на чистой PostgreSQL в docker")
    parser.add_argument("--mermaid", action="store_true", help="только напечатать erDiagram")
    parser.add_argument("--print-command", action="store_true",
                        help="показать команду проверки, ничего не запуская")
    args = parser.parse_args(argv)

    root = git_repo_root(Path(args.root).resolve())
    sql, files, warnings = collect_sql(root)
    for warning in dict.fromkeys(warnings):
        print("⚠ %s" % warning, file=sys.stderr)

    tables = parse_ddl(sql)

    if args.mermaid:
        print(render_mermaid(tables))
        return 0

    artifacts = {
        root / DB_SQL: build_sql(root, sql, files),
        root / ERD_MD: build_erd(tables),
    }

    relations = sum(1 for table in tables for column in table.columns if column.reference)

    if args.check:
        stale = [path for path, content in artifacts.items()
                 if not path.is_file() or path.read_text(encoding="utf-8") != content]
        if stale:
            print("Расходится с чанжлогом: %s" % ", ".join(
                path.relative_to(root).as_posix() for path in stale))
            print("Пересоберите: make db-schema")
            return 1
        print("db.sql и erd.md соответствуют чанжлогу: %d таблиц, %d %s" % (
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
    raise SystemExit(main())
