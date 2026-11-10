#!/usr/bin/env python3
"""Сбор контрактов API из кода: REST, GraphQL, gRPC → documentation/api/.

Что делает:
  * читает правила из `api-docs.toml`: источники → поверхности → include/exclude/artifacts;
  * для каждой поверхности берёт готовую спецификацию из сборки, если она есть в `artifacts`
    (REST — OpenAPI в JSON, GraphQL — SDL), иначе разбирает исходники статически;
  * пишет `index.md`, `rest.md`, `graphql.md`, `grpc.md` в каталог из `[output].dir`;
  * ничего не коммитит и не пушит: публикацией занимается workflow `docs → wiki`.

Использование:
  python3 .github/scripts/api_docs.py                     # пересобрать страницы по конфигу
  python3 .github/scripts/api_docs.py --check              # проверить актуальность (1 при расхождении)
  python3 .github/scripts/api_docs.py --out /tmp/api-docs  # собрать в другую папку
  python3 .github/scripts/api_docs.py --no-dates           # без обращения к git за датой коммита

Зависимости — только стандартная библиотека Python 3.11+ (`tomllib` для конфига).
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    tomllib = None

DEFAULT_REPO = "DirtyDocsTeam/DocsApp"
DEFAULT_REF = "main"
DEFAULT_CONFIG = "api-docs.toml"

SURFACE_KINDS = ("rest", "graphql", "grpc")
SURFACE_TITLE = {
    "rest": "REST",
    "graphql": "GraphQL",
    "grpc": "gRPC",
}
SURFACE_PAGE = {
    "rest": "rest.md",
    "graphql": "graphql.md",
    "grpc": "grpc.md",
}
INDEX_PAGE = "index.md"

# Адаптеры: (поверхность, framework) → имя парсера. Неизвестная пара не ломает сборку.
ADAPTERS = {
    ("rest", "quarkus"): "jvm-rest",
    ("rest", "jakarta-rest"): "jvm-rest",
    ("rest", "jaxrs"): "jvm-rest",
    ("rest", "jax-rs"): "jvm-rest",
    ("graphql", "quarkus"): "jvm-graphql",
    ("graphql", "microprofile-graphql"): "jvm-graphql",
    ("graphql", "microprofile"): "jvm-graphql",
    ("rest", "api-contracts"): "contract-yaml",
    ("rest", "contract-yaml"): "contract-yaml",
    ("grpc", "proto"): "proto",
    ("grpc", "quarkus"): "proto",
    ("grpc", "any"): "proto",
}

# Jakarta REST: имя аннотации параметра → место в запросе.
PARAM_LOCATION = {
    "PathParam": "path",
    "QueryParam": "query",
    "HeaderParam": "header",
    "CookieParam": "cookie",
    "MatrixParam": "matrix",
    "FormParam": "form",
    "BeanParam": "bean",
    "RequestBody": "body",
    "Body": "body",
    "BodyParam": "body",
}

HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE")

SECURITY_ANNOTATIONS = {
    "Authenticated": "требуется аутентификация",
    "PermitAll": "без аутентификации",
    "DenyAll": "доступ запрещён",
    "RolesAllowed": "роли",
}

GQL_SCALARS = {
    "String", "Int", "Long", "Short", "Byte", "Char", "Float", "Double", "Boolean", "ID",
    "BigDecimal", "BigInteger", "Date", "DateTime", "LocalDate", "LocalDateTime", "OffsetDateTime",
    "Instant", "ZonedDateTime", "Duration", "UUID", "URI", "URL", "Json", "JSON", "Object", "Number",
    "Time", "Timestamp", "Decimal",
}

MODIFIERS = {
    "public", "private", "protected", "internal", "static", "final", "abstract", "open", "override",
    "suspend", "inline", "operator", "infix", "tailrec", "external", "data", "sealed", "inner", "enum",
    "annotation", "companion", "lateinit", "const", "default", "synchronized", "native", "transient",
    "volatile", "value", "fun", "async", "partial", "readonly",
}


# ─────────────────────────── утилиты ───────────────────────────

def quote_path(path: str) -> str:
    return urllib.parse.quote(path, safe="/")


def git(*args: str, cwd: Path | None = None) -> str:
    res = subprocess.run(["git", *args], cwd=str(cwd) if cwd else None,
                         capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError("git %s: %s" % (" ".join(args), res.stderr.strip()))
    return res.stdout


def commit_info(root: Path) -> tuple[str, str]:
    """(короткий хэш, дата) текущего коммита; пустые строки, если git недоступен."""
    try:
        sha = git("rev-parse", "--short", "HEAD", cwd=root).strip()
        date = git("log", "-1", "--format=%cs", cwd=root).strip()
    except (RuntimeError, FileNotFoundError):
        return "", ""
    return sha, date


def md_cell(text: str) -> str:
    """Значение для ячейки таблицы: без переводов строк и незаэкранированных `|`."""
    clean = re.sub(r"\s+", " ", (text or "").replace("|", "\\|")).strip()
    return clean or "—"


def code(text: str) -> str:
    """Инлайн-код; безопасен для строк с обратными кавычками."""
    if not text:
        return "—"
    if "`" in text:
        return "`` %s ``" % text
    return "`%s`" % text


def collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def plural(n: int, one: str, few: str, many: str) -> str:
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return one
    if 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        return few
    return many


# ─────────────────────────── разбор исходников: лексер-лайт ───────────────────────────

def mask(text: str) -> str:
    """Заменяет содержимое комментариев и строк пробелами, сохраняя длину и переводы строк.

    Позиции в результате совпадают с позициями в исходнике, поэтому можно резать оригинал
    по индексам маски — так описания и значения по умолчанию остаются настоящими.
    """
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if ch == "/" and nxt == "/":
            while i < n and text[i] != "\n":
                out[i] = " "
                i += 1
        elif ch == "/" and nxt == "*":
            out[i] = " "
            if i + 1 < n:
                out[i + 1] = " "
            i += 2
            while i < n and not (text[i] == "*" and i + 1 < n and text[i + 1] == "/"):
                if text[i] != "\n":
                    out[i] = " "
                i += 1
            for k in range(i, min(i + 2, n)):
                out[k] = " "
            i += 2
        elif ch == '"':
            if text.startswith('"""', i):
                for k in range(i, min(i + 3, n)):
                    out[k] = " "
                i += 3
                while i < n and not text.startswith('"""', i):
                    if text[i] != "\n":
                        out[i] = " "
                    i += 1
                for k in range(i, min(i + 3, n)):
                    out[k] = " "
                i += 3
            else:
                i += 1
                while i < n and text[i] != '"':
                    if text[i] == "\\" and i + 1 < n:
                        out[i] = " "
                        i += 1
                    if i < n and text[i] != "\n":
                        out[i] = " "
                    i += 1
                i += 1
        elif ch == "'":
            i += 1
            while i < n and text[i] != "'":
                if text[i] == "\\" and i + 1 < n:
                    out[i] = " "
                    i += 1
                if i < n and text[i] != "\n":
                    out[i] = " "
                i += 1
            i += 1
        else:
            i += 1
    return "".join(out)


def match_forward(masked: str, pos: int, open_ch: str, close_ch: str) -> int:
    """Индекс парной закрывающей скобки для `masked[pos] == open_ch`; -1, если не нашли."""
    if pos >= len(masked) or masked[pos] != open_ch:
        return -1
    depth = 0
    i = pos
    while i < len(masked):
        if masked[i] == open_ch:
            depth += 1
        elif masked[i] == close_ch:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def split_top_level(masked: str, start: int, end: int) -> list[tuple[int, int]]:
    """Режет диапазон по запятым верхнего уровня (учитывая скобки и generic-уголки)."""
    parts: list[tuple[int, int]] = []
    round_ = square = curly = angle = 0
    seg = start
    i = start
    while i < end:
        ch = masked[i]
        if ch == "(":
            round_ += 1
        elif ch == ")":
            round_ = max(0, round_ - 1)
        elif ch == "[":
            square += 1
        elif ch == "]":
            square = max(0, square - 1)
        elif ch == "{":
            curly += 1
        elif ch == "}":
            curly = max(0, curly - 1)
        elif ch == "<" and i + 1 < end and (masked[i + 1].isalnum() or masked[i + 1] in "_?*"):
            angle += 1
        elif ch == ">" and angle > 0:
            angle -= 1
        elif ch == "," and not (round_ or square or curly or angle):
            parts.append((seg, i))
            seg = i + 1
        i += 1
    parts.append((seg, end))
    return [p for p in parts if masked[p[0]:p[1]].strip()]


@dataclass
class Annotation:
    name: str
    args: str
    start: int
    end: int


ANN_RE = re.compile(r"@([A-Za-z_][\w.$]*)")


def scan_annotations(masked: str, text: str) -> list[Annotation]:
    """Все аннотации в файле; аргументы берутся из оригинала, границы — из маски."""
    found: list[Annotation] = []
    for match in ANN_RE.finditer(masked):
        name = match.group(1).split(".")[-1]
        cursor = match.end()
        while cursor < len(masked) and masked[cursor] in " \t\r\n":
            cursor += 1
        args = ""
        end = match.end()
        if cursor < len(masked) and masked[cursor] == "(":
            close = match_forward(masked, cursor, "(", ")")
            if close > cursor:
                args = text[cursor + 1:close]
                end = close + 1
        found.append(Annotation(name, args, match.start(), end))
    return found


def annotations_before(masked: str, annotations: list[Annotation], pos: int) -> list[Annotation]:
    """Аннотации, стоящие вплотную перед объявлением (между ними только пробелы/модификаторы)."""
    by_end = {a.end: a for a in annotations}
    collected: list[Annotation] = []
    cursor = pos
    while True:
        j = cursor - 1
        while j >= 0 and masked[j] in " \t\r\n":
            j -= 1
        if j < 0:
            break
        end = j + 1
        if end in by_end:
            annotation = by_end[end]
            collected.append(annotation)
            cursor = annotation.start
            continue
        k = end
        while k > 0 and (masked[k - 1].isalnum() or masked[k - 1] in "_$"):
            k -= 1
        if masked[k:end] in MODIFIERS:
            cursor = k
            continue
        break
    collected.reverse()
    return collected


def ann_names(annotations: list[Annotation]) -> list[str]:
    return [a.name for a in annotations]


def ann_map(annotations: list[Annotation]) -> dict[str, str]:
    """Имя аннотации → значение: строковый литерал, иначе сам текст аргумента.

    `@Path("/x")` → `/x`, `@Produces(MediaType.APPLICATION_JSON)` → `MediaType.APPLICATION_JSON`.
    """
    result: dict[str, str] = {}
    for annotation in annotations:
        value = first_string(annotation.args) or collapse(annotation.args)
        result.setdefault(annotation.name, value)
    return result


def first_string(raw: str) -> str:
    match = re.search(r'"((?:[^"\\]|\\.)*)"', raw or "")
    return match.group(1) if match else ""


def named_arg(raw: str, key: str) -> str:
    match = re.search(r"\b%s\s*=\s*" % re.escape(key), raw or "")
    if not match:
        return ""
    tail = raw[match.end():]
    value = re.match(r'"((?:[^"\\]|\\.)*)"', tail)
    if value:
        return value.group(1)
    plain = re.match(r"[^,)\s]+", tail)
    return plain.group(0) if plain else ""


def strip_comment_block(raw: str) -> str:
    body = raw
    if body.startswith("/**"):
        body = body[3:]
    elif body.startswith("/*"):
        body = body[2:]
    if body.endswith("*/"):
        body = body[:-2]
    lines = []
    for line in body.splitlines():
        line = re.sub(r"^\s*\*+", "", line).strip()
        if line:
            lines.append(line)
    return collapse(" ".join(lines))


def doc_before(text: str, masked: str, annotations: list[Annotation], pos: int) -> str:
    """KDoc/Javadoc вплотную перед объявлением.

    Комментарий ищется в оригинале: в маске его содержимое затёрто пробелами, поэтому
    «шагать назад по пробелам» от объявления нельзя. Вместо этого берём ближайший `*/`
    и проверяем, что между ним и объявлением только аннотации и модификаторы.
    """
    end = text.rfind("*/", 0, pos)
    if end < 0:
        return ""
    gap = list(masked[end + 2:pos])
    for annotation in annotations:
        low = max(annotation.start, end + 2)
        high = min(annotation.end, pos)
        for k in range(low - (end + 2), high - (end + 2)):
            if 0 <= k < len(gap):
                gap[k] = " "
    tail = "".join(gap)
    if re.search(r"[;{}=]", tail) or re.search(r"\b(?:fun|val|var|class|interface|object)\b", tail):
        return ""
    start = text.rfind("/*", 0, end)
    return strip_comment_block(text[start:end + 2]) if start >= 0 else ""


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


# ─────────────────────────── модель JVM-исходников ───────────────────────────

@dataclass
class Param:
    name: str = ""
    type: str = ""
    default: str = ""
    required: bool = False
    location: str = ""
    description: str = ""
    annotations: list[str] = field(default_factory=list)


@dataclass
class Method:
    name: str
    line: int
    annotations: list[Annotation] = field(default_factory=list)
    params: list[Param] = field(default_factory=list)
    returns: str = ""
    doc: str = ""


@dataclass
class ClassDecl:
    name: str
    kind: str
    line: int
    annotations: list[Annotation] = field(default_factory=list)
    params: list[Param] = field(default_factory=list)
    properties: list[Param] = field(default_factory=list)
    methods: list[Method] = field(default_factory=list)
    doc: str = ""
    enum_values: list[str] = field(default_factory=list)


@dataclass
class SourceFile:
    path: Path
    rel: str
    text: str
    classes: list[ClassDecl] = field(default_factory=list)
    functions: list[Method] = field(default_factory=list)


CLASS_RE = re.compile(r"\b(class|interface|object)\s+([A-Za-z_]\w*)")
FUN_RE = re.compile(r"\bfun\s+(?:<[^>\n]{0,200}>\s*)?(?:[A-Za-z_][\w.]*\.)?([A-Za-z_]\w*)\s*\(")
JAVA_METHOD_RE = re.compile(
    r"(?:public|protected|private)\s+(?:static\s+|final\s+|synchronized\s+|abstract\s+|native\s+)*"
    r"([\w.$]+(?:\s*<[^;{}]*?>)?(?:\[\])?)\s+([A-Za-z_]\w*)\s*\(")
PROP_RE = re.compile(r"\b(?:val|var)\s+([A-Za-z_]\w*)\s*:")


def find_body(masked: str, pos: int) -> tuple[int, int]:
    """Границы тела класса после его заголовка; (-1, -1), если тела нет."""
    depth = 0
    limit = min(len(masked), pos + 4000)
    i = pos
    while i < limit:
        ch = masked[i]
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        elif ch == "<" and i + 1 < limit and (masked[i + 1].isalnum() or masked[i + 1] in "_?*"):
            depth += 1
        elif ch == ">" and depth > 0:
            depth -= 1
        elif ch == "{" and depth == 0:
            if re.search(r"\b(?:fun|val|var|class|interface|object)\b", masked[pos:i]):
                return -1, -1
            return i, match_forward(masked, i, "{", "}")
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
        i += 1
    return -1, -1


def top_level_index(masked: str, char: str, start: int = 0, end: int | None = None) -> int:
    end = len(masked) if end is None else end
    round_ = square = curly = angle = 0
    i = start
    while i < end:
        ch = masked[i]
        if ch == "(":
            round_ += 1
        elif ch == ")":
            round_ = max(0, round_ - 1)
        elif ch == "[":
            square += 1
        elif ch == "]":
            square = max(0, square - 1)
        elif ch == "{":
            curly += 1
        elif ch == "}":
            curly = max(0, curly - 1)
        elif ch == "<" and i + 1 < end and (masked[i + 1].isalnum() or masked[i + 1] in "_?*"):
            angle += 1
        elif ch == ">" and angle > 0:
            angle -= 1
        elif ch == char and not (round_ or square or curly or angle):
            return i
        i += 1
    return -1


def last_ident(text: str) -> str:
    idents = re.findall(r"[A-Za-z_]\w*", text)
    return idents[-1] if idents else ""


def _args_of(annotations: list[Annotation], name: str) -> str:
    for annotation in annotations:
        if annotation.name == name:
            return annotation.args
    return ""


def parse_params(masked: str, text: str, annotations: list[Annotation],
                 start: int, end: int) -> list[Param]:
    params: list[Param] = []
    for seg_start, seg_end in split_top_level(masked, start, end):
        local = list(masked[seg_start:seg_end])
        own = [a for a in annotations if a.start >= seg_start and a.end <= seg_end]
        for annotation in own:
            for k in range(annotation.start - seg_start, annotation.end - seg_start):
                local[k] = " "
        clean = "".join(local)
        original = text[seg_start:seg_end]

        colon = top_level_index(clean, ":")
        equals = top_level_index(clean, "=")
        param = Param(annotations=ann_names(own))
        if colon >= 0 and (equals < 0 or colon < equals):
            param.name = last_ident(clean[:colon])
            type_end = equals if equals > colon else len(clean)
            param.type = collapse(clean[colon + 1:type_end])
            if equals >= 0:
                param.default = collapse(original[equals + 1:])
        else:
            param.name = last_ident(clean)
            head = clean[:clean.rfind(param.name)] if param.name else clean
            head = re.sub(r"\b(?:final|val|var|const)\b", " ", head).strip(" ,")
            param.type = collapse(head)
        if not param.type:
            param.type = "—"
        value = ann_map(own).get("DefaultValue")
        if value:
            param.default = '"%s"' % value
        param.required = not param.default and not param.type.endswith("?")
        exposed = ann_map(own)
        if exposed.get("Name"):
            param.name = exposed["Name"]
        for annotation in own:
            if annotation.name in PARAM_LOCATION:
                param.location = PARAM_LOCATION[annotation.name]
        param.description = exposed.get("Description") or named_arg(
            _args_of(own, "Parameter"), "description")
        params.append(param)
    return params


def method_return_type(masked: str, text: str, close_paren: int) -> tuple[str, bool]:
    """Тип возврата после `)` + признак «тело через `=`» (Kotlin expression body)."""
    cursor = close_paren + 1
    while cursor < len(masked) and masked[cursor] in " \t":
        cursor += 1
    if cursor < len(masked) and masked[cursor] == ":":
        line_end = masked.find("\n", cursor)
        line_end = len(masked) if line_end < 0 else line_end
        limit = line_end
        stop = top_level_index(masked, "{", cursor, limit)
        if stop >= 0:
            limit = stop
        equals = top_level_index(masked, "=", cursor, limit)
        if equals >= 0:
            limit = equals
        return collapse(masked[cursor + 1:limit]), False
    if cursor < len(masked) and masked[cursor] == "=":
        return "", True
    return "", False


def parse_methods(masked: str, text: str, annotations: list[Annotation],
                  start: int, end: int) -> list[Method]:
    methods: list[Method] = []

    def add(pos: int, name: str, open_paren: int) -> None:
        close = match_forward(masked, open_paren, "(", ")")
        if close < 0:
            return
        own = annotations_before(masked, annotations, pos)
        params = parse_params(masked, text, annotations, open_paren + 1, close)
        returns, _ = method_return_type(masked, text, close)
        methods.append(Method(name=name, line=line_of(text, pos), annotations=own,
                              params=params, returns=returns,
                              doc=doc_before(text, masked, annotations, pos)))

    for match in FUN_RE.finditer(masked, start, end):
        j = match.start() - 1
        while j >= start and masked[j] in " \t":
            j -= 1
        if j >= start and masked[j] in "(,=":
            continue  # лямбда вида `fun(x) = …`, а не объявление
        add(match.start(), match.group(1), match.end() - 1)

    for match in JAVA_METHOD_RE.finditer(masked, start, end):
        pos = match.start()
        if any(m.line == line_of(text, pos) and m.name == match.group(2) for m in methods):
            continue
        if re.match(r"\s*(?:class|interface|enum|record)\b", masked[match.end():match.end() + 40]):
            continue
        method = Method(name=match.group(2), line=line_of(text, pos),
                        annotations=annotations_before(masked, annotations, pos))
        open_paren = match.end() - 1
        close = match_forward(masked, open_paren, "(", ")")
        if close > 0:
            method.params = parse_params(masked, text, annotations, open_paren + 1, close)
        method.returns = collapse(match.group(1))
        method.doc = doc_before(text, masked, annotations, pos)
        methods.append(method)

    return methods


def parse_source(path: Path, rel: str, text: str) -> SourceFile:
    masked = mask(text)
    annotations = scan_annotations(masked, text)
    source = SourceFile(path=path, rel=rel, text=text)

    for match in CLASS_RE.finditer(masked):
        if masked[max(0, match.start() - 2):match.start()] == "::":
            continue
        name = match.group(2)
        own = annotations_before(masked, annotations, match.start())
        body_start, body_end = find_body(masked, match.end())
        decl = ClassDecl(name=name, kind=match.group(1), line=line_of(text, match.start()),
                         annotations=own,
                         doc=doc_before(text, masked, annotations, match.start()))
        cursor = match.end()
        while cursor < len(masked) and masked[cursor] in " \t\r\n":
            cursor += 1
        if cursor < len(masked) and masked[cursor] == "<":
            close = match_forward(masked, cursor, "<", ">")
            cursor = close + 1 if close > 0 else cursor
        while cursor < len(masked) and masked[cursor] in " \t":
            cursor += 1
        if cursor < len(masked) and masked[cursor] == "(":
            close = match_forward(masked, cursor, "(", ")")
            if close > 0:
                decl.params = parse_params(masked, text, annotations, cursor + 1, close)
        if body_start >= 0:
            decl.methods = parse_methods(masked, text, annotations, body_start, body_end)
            decl.properties = parse_properties(masked, text, annotations, body_start, body_end)
            if decl.kind == "class" and re.search(r"\benum\s*$",
                                                 masked[max(0, match.start() - 12):match.start()]):
                decl.enum_values = parse_enum_values(masked, body_start, body_end)
        source.classes.append(decl)

    return source


def parse_properties(masked: str, text: str, annotations: list[Annotation],
                     start: int, end: int) -> list[Param]:
    props: list[Param] = []
    for match in PROP_RE.finditer(masked, start, end):
        line_start = masked.rfind("\n", start, match.start()) + 1
        if re.search(r"\bfun\b", masked[line_start:match.start()]):
            continue
        colon = match.end() - 1
        line_end = masked.find("\n", colon)
        line_end = end if line_end < 0 or line_end > end else line_end
        equals = top_level_index(masked, "=", colon, line_end)
        type_end = equals if equals > colon else line_end
        own = annotations_before(masked, annotations, match.start())
        props.append(Param(
            name=match.group(1),
            type=collapse(masked[colon + 1:type_end]),
            default=collapse(text[equals + 1:line_end]) if equals > colon else "",
            annotations=ann_names(own),
            description=ann_map(own).get("Description", ""),
        ))
    return props


def parse_enum_values(masked: str, start: int, end: int) -> list[str]:
    body = masked[start + 1:max(start + 1, end)]
    values: list[str] = []
    for seg_start, seg_end in split_top_level(body, 0, len(body)):
        chunk = body[seg_start:seg_end]
        chunk = re.sub(r"\(.*", "", chunk, flags=re.S)
        name = last_ident(chunk)
        if name and name not in {"enum", "const"}:
            values.append(name)
    return [value for value in values if value]
    return values


# ─────────────────────────── REST ───────────────────────────

@dataclass
class Operation:
    method: str
    path: str
    handler: str
    line: int
    file: str = ""
    description: str = ""
    params: list[Param] = field(default_factory=list)
    consumes: str = ""
    produces: str = ""
    returns: str = ""
    request_body: str = ""
    responses: list[tuple[str, str]] = field(default_factory=list)
    security: str = ""


@dataclass
class Resource:
    name: str
    base_path: str
    line: int
    file: str = ""
    host: str = ""
    description: str = ""
    security: str = ""
    operations: list[Operation] = field(default_factory=list)


def join_path(base: str, sub: str) -> str:
    parts = [p.strip("/") for p in (base or "", sub or "")]
    joined = "/".join(p for p in parts if p)
    return "/" + joined if joined else "/"


def security_of(annotations: list[Annotation]) -> str:
    labels: list[str] = []
    for annotation in annotations:
        label = SECURITY_ANNOTATIONS.get(annotation.name)
        if not label:
            continue
        if annotation.name == "RolesAllowed":
            roles = re.findall(r'"([^"]*)"', annotation.args) or re.findall(r"[A-Za-z_][\w.]*", annotation.args)
            if roles:
                label = "роли: %s" % ", ".join(code(role) for role in roles)
        labels.append(label)
    return "; ".join(dict.fromkeys(labels))


def collect_rest(sources: list[SourceFile]) -> tuple[list[Resource], list[str]]:
    resources: list[Resource] = []
    warnings: list[str] = []
    for source in sources:
        for decl in source.classes:
            base = ann_map(decl.annotations).get("Path")
            if base is None:
                continue
            class_security = security_of(decl.annotations)
            class_consumes = ann_map(decl.annotations).get("Consumes", "")
            class_produces = ann_map(decl.annotations).get("Produces", "")
            resource = Resource(name=decl.name, base_path=join_path("", base), line=decl.line,
                                file=source.rel,
                                description=decl.doc or ann_map(decl.annotations).get("Description", ""),
                                security=class_security)
            for method in decl.methods:
                verbs = [name for name in ann_names(method.annotations) if name in HTTP_METHODS]
                if not verbs:
                    continue
                verb = verbs[0]
                own = ann_map(method.annotations)
                path = join_path(resource.base_path, own.get("Path", ""))
                operation = Operation(
                    method=verb,
                    path=path,
                    handler=method.name,
                    line=method.line,
                    file=source.rel,
                    description=(named_arg(_annotation_args(method, "Operation"), "summary")
                                 or named_arg(_annotation_args(method, "Operation"), "description")
                                 or method.doc),
                    params=method.params,
                    consumes=own.get("Consumes", class_consumes),
                    produces=own.get("Produces", class_produces),
                    returns=method.returns,
                    security=security_of(method.annotations) or class_security,
                )
                classify_params(operation)
                body = next((p for p in operation.params if p.location == "body"), None)
                operation.request_body = body.type if body else ""
                operation.responses = responses_of(method, operation)
                resource.operations.append(operation)
            if not resource.operations:
                warnings.append("%s: `@Path(\"%s\")` без HTTP-методов — ресурс пропущен"
                                % (source.rel, resource.base_path))
                continue
            resources.append(resource)
    resources.sort(key=lambda r: (r.base_path, r.name))
    for resource in resources:
        resource.operations.sort(key=lambda o: (o.path, HTTP_METHODS.index(o.method)
                                                if o.method in HTTP_METHODS else 99))
    return resources, warnings


def _annotation_args(method: Method, name: str) -> str:
    for annotation in method.annotations:
        if annotation.name == name:
            return annotation.args
    return ""


def classify_params(operation: Operation) -> None:
    """Доразмечает параметры, у которых нет аннотации места."""
    unmarked = [p for p in operation.params if not p.location]
    for param in unmarked:
        if operation.method in {"POST", "PUT", "PATCH"} and len(unmarked) == 1:
            param.location = "body"
    for param in operation.params:
        if param.location == "path":
            param.required = True


def responses_of(method: Method, operation: Operation) -> list[tuple[str, str]]:
    declared: list[tuple[str, str]] = []
    for annotation in method.annotations:
        if annotation.name != "APIResponse":
            continue
        code_value = named_arg(annotation.args, "responseCode") or named_arg(annotation.args, "code") or "200"
        description = named_arg(annotation.args, "description")
        declared.append((code_value, description))
    if declared:
        return declared
    if not operation.returns:
        return [("200", "тип не объявлен в коде")] if operation.method != "DELETE" \
            else [("204", "без тела")]
    if operation.returns in {"Unit", "void", "Nothing"}:
        return [("204", "без тела")]
    return [("200", operation.returns)]


# ─────────────────────────── GraphQL ───────────────────────────

@dataclass
class GqlField:
    kind: str
    name: str
    returns: str
    line: int
    file: str = ""
    args: list[Param] = field(default_factory=list)
    description: str = ""


@dataclass
class GqlType:
    name: str
    kind: str
    line: int
    description: str = ""
    fields: list[Param] = field(default_factory=list)
    values: list[str] = field(default_factory=list)


def collect_graphql(sources: list[SourceFile]) -> tuple[list[GqlField], list[GqlType], list[str]]:
    fields: list[GqlField] = []
    all_types: dict[str, GqlType] = {}
    warnings: list[str] = []

    for source in sources:
        for decl in source.classes:
            kind = None
            if "Input" in ann_names(decl.annotations) or "InputType" in ann_names(decl.annotations):
                kind = "input"
            elif decl.enum_values:
                kind = "enum"
            elif decl.kind == "interface":
                kind = "interface"
            elif decl.params or decl.properties:
                kind = "type"
            if kind:
                all_types.setdefault(decl.name, GqlType(
                    name=decl.name, kind=kind, line=decl.line,
                    description=decl.doc or ann_map(decl.annotations).get("Description", ""),
                    fields=[p for p in (decl.params + decl.properties) if p.name],
                    values=decl.enum_values,
                ))
            for method in decl.methods:
                names = ann_names(method.annotations)
                field_kind = next((k for k in ("query", "mutation", "subscription")
                                   if k.capitalize() in names), None)
                if not field_kind:
                    continue
                if "Ignore" in names:
                    continue
                own = ann_map(method.annotations)
                fields.append(GqlField(
                    kind=field_kind,
                    name=own.get("Name") or method.name,
                    returns=method.returns or "String",
                    line=method.line,
                    file=source.rel,
                    args=method.params,
                    description=own.get("Description") or method.doc,
                ))

    fields.sort(key=lambda f: (("query", "mutation", "subscription").index(f.kind), f.name))
    if not fields:
        warnings.append("GraphQL: в исходниках не найдено ни `@Query`, ни `@Mutation`")

    reachable = reachable_types(fields, all_types)
    return fields, [all_types[name] for name in sorted(reachable)], warnings


def type_names(raw: str) -> list[str]:
    return [name for name in re.findall(r"[A-Za-z_]\w*", raw or "")]


def reachable_types(fields: list[GqlField], known: dict[str, GqlType]) -> list[str]:
    """Типы, достижимые из полей запросов/мутаций (иначе в документ попадут внутренние классы)."""
    queue: list[str] = []
    for field in fields:
        queue.extend(type_names(field.returns))
        for arg in field.args:
            queue.extend(type_names(arg.type))
    seen: set[str] = set()
    while queue:
        name = queue.pop(0)
        if name in seen or name not in known or name in GQL_SCALARS:
            continue
        seen.add(name)
        for item in known[name].fields:
            queue.extend(type_names(item.type))
    return sorted(seen)


# ─────────────────────────── proto / gRPC ───────────────────────────

PROTO_TOKEN_RE = re.compile(r"""
    (?P<comment>//[^\n]*|/\*.*?\*/)
  | (?P<string>"(?:[^"\\\n]|\\.)*")
  | (?P<number>[-+]?\d+(?:\.\d+)?)
  | (?P<ident>[A-Za-z_][\w.]*)
  | (?P<symbol>[{}()\[\]<>=;,/])
  | (?P<other>[^\s])
""", re.S | re.X)


@dataclass
class Token:
    kind: str
    value: str
    line: int
    doc: str = ""


@dataclass
class ProtoFieldDecl:
    name: str
    type: str
    number: str
    cardinality: str = ""
    description: str = ""


@dataclass
class ProtoMessage:
    name: str
    line: int
    description: str = ""
    fields: list[ProtoFieldDecl] = field(default_factory=list)
    oneofs: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class ProtoEnum:
    name: str
    line: int
    description: str = ""
    values: list[tuple[str, str, str]] = field(default_factory=list)


@dataclass
class Rpc:
    name: str
    request: str
    response: str
    streaming: str
    line: int
    description: str = ""


@dataclass
class ProtoService:
    name: str
    line: int
    description: str = ""
    rpcs: list[Rpc] = field(default_factory=list)


@dataclass
class ProtoDoc:
    rel: str
    package: str = ""
    syntax: str = ""
    services: list[ProtoService] = field(default_factory=list)
    messages: list[ProtoMessage] = field(default_factory=list)
    enums: list[ProtoEnum] = field(default_factory=list)


def tokenize_proto(text: str) -> list[Token]:
    tokens: list[Token] = []
    line = 1
    pending: list[str] = []
    for match in PROTO_TOKEN_RE.finditer(text):
        kind = match.lastgroup or "other"
        value = match.group(0)
        if kind == "comment":
            if value.startswith("//"):
                pending.append(value.lstrip("/").strip())
            else:
                body = value[2:-2]
                pending.extend(re.sub(r"^\s*\*+", "", ln).strip() for ln in body.splitlines())
            line += value.count("\n")
            continue
        if kind == "other":
            line += value.count("\n")
            continue
        doc = collapse(" ".join(part for part in pending if part))
        pending = []
        tokens.append(Token(kind=kind, value=value, line=line, doc=doc if kind == "ident" else ""))
        line += value.count("\n")
    return tokens


class ProtoParser:
    def __init__(self, tokens: list[Token], rel: str):
        self.tokens = tokens
        self.pos = 0
        self.doc = ProtoDoc(rel=rel)

    # --- навигация ---
    def peek(self, offset: int = 0) -> Token | None:
        index = self.pos + offset
        return self.tokens[index] if 0 <= index < len(self.tokens) else None

    def advance(self) -> Token | None:
        token = self.peek()
        self.pos += 1
        return token

    def at_symbol(self, value: str) -> bool:
        token = self.peek()
        return bool(token and token.kind == "symbol" and token.value == value)

    def at_ident(self, value: str) -> bool:
        token = self.peek()
        return bool(token and token.kind == "ident" and token.value == value)

    def skip_symbol(self, value: str) -> None:
        if self.at_symbol(value):
            self.advance()

    def skip_statement(self) -> None:
        """Пропускает до `;` или до закрытия текущего блока."""
        depth = 0
        while (token := self.peek()) is not None:
            if token.kind == "symbol":
                if token.value in "{[(":
                    depth += 1
                elif token.value in "}])":
                    if depth == 0:
                        return
                    depth -= 1
                elif token.value == ";" and depth == 0:
                    self.pos += 1
                    return
            self.pos += 1

    def skip_block(self) -> None:
        if not self.at_symbol("{"):
            return
        depth = 0
        while (token := self.peek()) is not None:
            self.pos += 1
            if token.kind == "symbol" and token.value == "{":
                depth += 1
            elif token.kind == "symbol" and token.value == "}":
                depth -= 1
                if depth == 0:
                    return

    # --- разбор файла ---
    def parse(self) -> ProtoDoc:
        while (token := self.peek()) is not None:
            if token.kind == "ident" and token.value == "syntax":
                self.advance()
                if self.at_symbol("="):
                    self.advance()
                value = self.peek()
                if value and value.kind == "string":
                    self.doc.syntax = value.value.strip('"')
                    self.advance()
                self.skip_statement()
            elif token.kind == "ident" and token.value == "package":
                self.advance()
                name = self.peek()
                if name and name.kind == "ident":
                    self.doc.package = name.value
                    self.advance()
                self.skip_statement()
            elif token.kind == "ident" and token.value == "service":
                self.parse_service()
            elif token.kind == "ident" and token.value == "message":
                self.parse_message("")
            elif token.kind == "ident" and token.value == "enum":
                self.parse_enum("")
            else:
                self.pos += 1
        return self.doc

    def parse_service(self) -> None:
        header = self.advance()
        name = self.peek()
        if not name or name.kind != "ident":
            return
        self.advance()
        service = ProtoService(name=name.value, line=header.line if header else 0,
                               description=(header.doc if header else "") or name.doc)
        if self.at_symbol("{"):
            self.advance()
            while (token := self.peek()) is not None:
                if token.kind == "symbol" and token.value == "}":
                    self.advance()
                    break
                if token.kind == "ident" and token.value == "rpc":
                    self.parse_rpc(service)
                else:
                    self.advance()
        self.doc.services.append(service)

    def parse_rpc(self, service: ProtoService) -> None:
        header = self.advance()
        name = self.peek()
        if not name or name.kind != "ident":
            return
        self.advance()
        if not self.at_symbol("("):
            return
        self.advance()
        client_stream = self.at_ident("stream")
        if client_stream:
            self.advance()
        request = self.advance()
        self.skip_symbol(")")
        if self.at_ident("returns"):
            self.advance()
        self.skip_symbol("(")
        server_stream = self.at_ident("stream")
        if server_stream:
            self.advance()
        response = self.advance()
        self.skip_symbol(")")
        if server_stream and client_stream:
            streaming = "bidi"
        elif client_stream:
            streaming = "client"
        elif server_stream:
            streaming = "server"
        else:
            streaming = "unary"
        service.rpcs.append(Rpc(
            name=name.value,
            request=request.value if request and request.kind == "ident" else "—",
            response=response.value if response and response.kind == "ident" else "—",
            streaming=streaming,
            line=header.line if header else 0,
            description=header.doc or name.doc or "",
        ))
        if self.at_symbol("{"):
            self.skip_block()
        elif self.at_symbol(";"):
            self.advance()

    def parse_message(self, prefix: str) -> None:
        header = self.advance()
        name_token = self.peek()
        if not name_token or name_token.kind != "ident":
            return
        self.advance()
        full_name = "%s.%s" % (prefix, name_token.value) if prefix else name_token.value
        message = ProtoMessage(name=full_name, line=header.line if header else 0,
                               description=(header.doc or name_token.doc or ""))
        self.doc.messages.append(message)
        if not self.at_symbol("{"):
            return
        self.advance()
        while (token := self.peek()) is not None:
            if token.kind == "symbol" and token.value == "}":
                self.advance()
                return
            if token.kind == "ident" and token.value in {"message", "enum"}:
                if token.value == "message":
                    self.parse_message(full_name)
                else:
                    self.parse_enum(full_name)
                continue
            if token.kind == "ident" and token.value == "oneof":
                self.parse_oneof(message)
                continue
            if token.kind == "ident" and token.value in {"option", "reserved", "extensions"}:
                self.skip_statement()
                continue
            field = self.parse_field(message)
            if not field:
                self.pos += 1

    def parse_oneof(self, message: ProtoMessage) -> None:
        self.advance()
        name_token = self.peek()
        if not name_token or name_token.kind != "ident":
            return
        self.advance()
        group = name_token.value
        message.oneofs.setdefault(group, [])
        if not self.at_symbol("{"):
            return
        self.advance()
        while (token := self.peek()) is not None:
            if token.kind == "symbol" and token.value == "}":
                self.advance()
                return
            field = self.parse_field(message, cardinality="oneof: %s" % group)
            if not field:
                self.pos += 1

    def parse_field(self, message: ProtoMessage, cardinality: str = "") -> bool:
        start = self.pos
        label = ""
        token = self.peek()
        if token and token.kind == "ident" and token.value in {"optional", "repeated", "required"}:
            label = token.value
            self.advance()
        type_token = self.peek()
        if not type_token:
            return False
        if type_token.kind == "ident" and type_token.value == "map":
            self.advance()
            if self.at_symbol("<"):
                self.advance()
                key = self.peek()
                self.advance() if key else None
                if self.at_symbol(","):
                    self.advance()
                value = self.peek()
                self.advance() if value else None
                if self.at_symbol(">"):
                    self.advance()
                type_text = "map<%s, %s>" % (key.value if key else "?",
                                             value.value if value else "?")
            else:
                self.pos = start
                return False
        elif type_token.kind in {"ident"}:
            type_text = type_token.value
            self.advance()
        else:
            self.pos = start
            return False
        name_token = self.peek()
        if not name_token or name_token.kind != "ident":
            self.pos = start
            return False
        self.advance()
        number = ""
        if self.at_symbol("="):
            self.advance()
            number_token = self.peek()
            if number_token and number_token.kind == "number":
                number = number_token.value
                self.advance()
        if self.at_symbol("["):
            depth = 0
            while (sym := self.peek()) is not None:
                self.advance()
                if sym.kind == "symbol" and sym.value == "[":
                    depth += 1
                elif sym.kind == "symbol" and sym.value == "]":
                    depth -= 1
                    if depth == 0:
                        break
        if self.at_symbol(";"):
            self.advance()
        message.fields.append(ProtoFieldDecl(
            name=name_token.value,
            type=type_text,
            number=number or "—",
            cardinality=cardinality or label,
            description=(token.doc if token else "") or name_token.doc or "",
        ))
        return True

    def parse_enum(self, prefix: str) -> None:
        header = self.advance()
        name_token = self.peek()
        if not name_token or name_token.kind != "ident":
            return
        self.advance()
        full_name = "%s.%s" % (prefix, name_token.value) if prefix else name_token.value
        enum = ProtoEnum(name=full_name, line=header.line if header else 0,
                         description=(header.doc or name_token.doc or ""))
        self.doc.enums.append(enum)
        if not self.at_symbol("{"):
            return
        self.advance()
        while (token := self.peek()) is not None:
            if token.kind == "symbol" and token.value == "}":
                self.advance()
                return
            if token.kind == "ident" and token.value in {"option", "reserved"}:
                self.skip_statement()
                continue
            if token.kind != "ident":
                self.advance()
                continue
            value_name = token.value
            description = token.doc or ""
            self.advance()
            number = ""
            if self.at_symbol("="):
                self.advance()
                number_token = self.peek()
                if number_token and number_token.kind == "number":
                    number = number_token.value
                    self.advance()
            self.skip_statement()
            enum.values.append((value_name, number or "—", description))


def parse_proto(path: Path, rel: str, text: str) -> ProtoDoc:
    return ProtoParser(tokenize_proto(text), rel).parse()


# ─────────────────── декларативные контракты (YAML) ───────────────────
#
# Для сервисов, чей контракт ещё не выражен кодом (или выражен не аннотациями), допускается
# декларативный файл рядом с сервисом — как `backend/s3-gateway/api-contracts.yaml`.
# Поддерживается подмножество YAML: отображения, списки, скаляры и блочные строки (`|`, `>`).
# Всё остальное (flow-стиль `{}`/`[]`, якоря, теги, несколько документов) — ошибка с номером
# строки: тихо неверный контракт хуже громкой ошибки, а полноценный YAML-парсер в стандартную
# библиотеку Python не входит.


class YamlSubsetError(ValueError):
    """Синтаксис вне поддерживаемого подмножества YAML."""


def yaml_scalar(raw: str):
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    if value in {"null", "~", ""}:
        return None
    return value


class YamlSubset:
    """Минимальный YAML-читатель под декларативные контракты."""

    def __init__(self, text: str, where: str = ""):
        self.where = where or "yaml"
        self.lines: list[tuple[int, str, int]] = []
        for number, raw in enumerate(text.splitlines(), start=1):
            if "\t" in raw[:len(raw) - len(raw.lstrip(" \t"))]:
                raise YamlSubsetError("%s:%d: табуляция в отступе не поддерживается"
                                      % (self.where, number))
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("---"):
                raise YamlSubsetError("%s:%d: несколько документов в одном файле не поддерживаются"
                                      % (self.where, number))
            indent = len(raw) - len(raw.lstrip(" "))
            self.lines.append((indent, stripped, number))
        self.pos = 0

    def parse(self) -> dict:
        if not self.lines:
            return {}
        value = self.parse_node(self.lines[0][0])
        if self.pos < len(self.lines):
            _, text, number = self.lines[self.pos]
            raise YamlSubsetError("%s:%d: неожиданная строка `%s`" % (self.where, number, text))
        if not isinstance(value, dict):
            raise YamlSubsetError("%s: на верхнем уровне ожидалось отображение "
                                  "(`сервис:` → `host`/`paths`)" % self.where)
        return value

    def parse_node(self, indent: int):
        _, text, _ = self.lines[self.pos]
        if text == "-" or text.startswith("- "):
            return self.parse_sequence(indent)
        return self.parse_mapping(indent)

    def parse_mapping(self, indent: int, seed: tuple[str, str, int] | None = None) -> dict:
        result: dict = {}
        if seed is not None:
            key, rest, number = seed
            result[key] = self.parse_value(rest, indent, number)
        while self.pos < len(self.lines):
            line_indent, text, number = self.lines[self.pos]
            if line_indent != indent or text == "-" or text.startswith("- "):
                break
            key, rest = self.split_key(text, number)
            self.pos += 1
            if key in result:
                raise YamlSubsetError("%s:%d: повторяющийся ключ `%s`" % (self.where, number, key))
            result[key] = self.parse_value(rest, indent, number)
        return result

    def parse_sequence(self, indent: int) -> list:
        items: list = []
        while self.pos < len(self.lines):
            line_indent, text, number = self.lines[self.pos]
            if line_indent != indent or not (text == "-" or text.startswith("- ")):
                break
            self.pos += 1
            body = text[1:].strip()
            if not body:
                if self.pos < len(self.lines) and self.lines[self.pos][0] > indent:
                    items.append(self.parse_node(self.lines[self.pos][0]))
                else:
                    items.append(None)
                continue
            if ":" in body and not body.startswith(("\"", "'")):
                key, rest = self.split_key(body, number)
                items.append(self.parse_mapping(indent + len(text) - len(body),
                                                seed=(key, rest, number)))
            else:
                items.append(yaml_scalar(body))
        return items

    def parse_value(self, rest: str, indent: int, number: int):
        if rest in {"|", "|-", "|+", ">", ">-", ">+"}:
            return self.parse_block_scalar(rest, indent)
        if rest:
            return yaml_scalar(rest)
        if self.pos < len(self.lines):
            next_indent, next_text, _ = self.lines[self.pos]
            if next_indent > indent:
                return self.parse_node(next_indent)
            if next_indent == indent and (next_text == "-" or next_text.startswith("- ")):
                return self.parse_sequence(indent)
        return None

    def parse_block_scalar(self, style: str, indent: int) -> str:
        collected: list[str] = []
        while self.pos < len(self.lines) and self.lines[self.pos][0] > indent:
            collected.append(self.lines[self.pos][1])
            self.pos += 1
        return collapse(" ".join(collected)) if style.startswith(">") else "\n".join(collected)

    def split_key(self, text: str, number: int) -> tuple[str, str]:
        if text[0] in "&*!?%":
            raise YamlSubsetError("%s:%d: конструкция `%s` не поддерживается"
                                  % (self.where, number, text[0]))
        if ":" not in text:
            raise YamlSubsetError("%s:%d: ожидалось `ключ: значение`, получено `%s`"
                                  % (self.where, number, text))
        key, _, rest = text.partition(":")
        key = key.strip().strip("\"'")
        if not key:
            raise YamlSubsetError("%s:%d: пустой ключ" % (self.where, number))
        value = rest.strip()
        if value.startswith(("[", "{")):
            raise YamlSubsetError("%s:%d: flow-стиль (`%s`) не поддерживается — пишите блоками"
                                  % (self.where, number, value))
        return key, value


CONTRACT_KEYS = {"host", "description", "paths"}
CONTRACT_ENDPOINT_KEYS = {"path", "method", "type", "description", "summary", "headers"}


def parse_contract_file(path: Path, rel: str) -> tuple[list[Resource], list[str]]:
    """Декларативный REST-контракт: `сервис` → `host` + список `paths`.

    Один файл описывает один сервис (или несколько — по блоку на сервис). Для каждого пути
    доступны `path`, `method`, `type` (что отдаёт/принимает), `description`/`summary` и
    `headers`; шаблонные сегменты вида `{resource_id}` становятся path-параметрами.
    """
    document = YamlSubset(path.read_text(encoding="utf-8"), rel).parse()
    resources: list[Resource] = []
    warnings: list[str] = []

    for name, specification in document.items():
        if not isinstance(specification, dict):
            warnings.append("%s: `%s` описан не отображением — пропущен" % (rel, name))
            continue
        unknown = sorted(set(specification) - CONTRACT_KEYS)
        if unknown:
            warnings.append("%s: у `%s` неизвестные ключи: %s" % (rel, name, ", ".join(unknown)))
        endpoints = specification.get("paths") or []
        if not isinstance(endpoints, list):
            warnings.append("%s: у `%s` `paths` должен быть списком — пропущен" % (rel, name))
            continue
        resource = Resource(
            name=str(name), base_path="", line=0, file=rel,
            host=str(specification.get("host") or ""),
            description=collapse(str(specification.get("description") or "")),
        )
        for index, endpoint in enumerate(endpoints, start=1):
            if not isinstance(endpoint, dict):
                warnings.append("%s: `%s` — `paths[%d]` не отображение, пропущен"
                                % (rel, name, index))
                continue
            unknown = sorted(set(endpoint) - CONTRACT_ENDPOINT_KEYS)
            if unknown:
                warnings.append("%s: `%s` — `paths[%d]` неизвестные ключи: %s"
                                % (rel, name, index, ", ".join(unknown)))
            route = str(endpoint.get("path") or "").strip()
            if not route:
                warnings.append("%s: `%s` — `paths[%d]` без `path`, пропущен" % (rel, name, index))
                continue
            method = str(endpoint.get("method") or "GET").strip().upper()
            media = collapse(str(endpoint.get("type") or ""))
            headers = endpoint.get("headers") or []
            if isinstance(headers, str):
                headers = [headers]
            params = [Param(name=str(header), location="header", type="string", required=True)
                      for header in headers if str(header).strip()]
            for placeholder in re.findall(r"\{([^}]+)\}", route):
                params.append(Param(name=placeholder, location="path", type="string",
                                    required=True))
            resource.operations.append(Operation(
                method=method, path=route, handler="", line=0, file=rel,
                description=collapse(str(endpoint.get("description")
                                         or endpoint.get("summary") or "")),
                params=params,
                produces=media if method in {"GET", "HEAD", "DELETE", "OPTIONS"} else "",
                consumes=media if method in {"POST", "PUT", "PATCH"} else "",
            ))
        if resource.operations:
            resources.append(resource)
        else:
            warnings.append("%s: у `%s` нет ни одного пригодного `paths`" % (rel, name))

    resources.sort(key=lambda item: item.name)
    return resources, warnings


# ─────────────────────────── артефакты сборки ───────────────────────────

def load_openapi(path: Path) -> tuple[list[Operation], str]:
    document = json.loads(path.read_text(encoding="utf-8"))
    operations: list[Operation] = []
    for raw_path, item in (document.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        for verb in ("get", "post", "put", "patch", "delete", "head", "options", "trace"):
            operation = item.get(verb)
            if not isinstance(operation, dict):
                continue
            params = [Param(name=p.get("name", ""), location=p.get("in", ""),
                            type=_openapi_type(p.get("schema")), required=bool(p.get("required")),
                            description=p.get("description", ""))
                      for p in (operation.get("parameters") or []) if isinstance(p, dict)]
            body = operation.get("requestBody") or {}
            content = body.get("content") or {}
            request_body = ""
            if content:
                media, spec = next(iter(content.items()))
                request_body = "%s (%s)" % (_openapi_type((spec or {}).get("schema")), media)
            responses: list[tuple[str, str]] = []
            for status, spec in (operation.get("responses") or {}).items():
                spec = spec if isinstance(spec, dict) else {}
                media = next(iter((spec.get("content") or {"": {}}).items()))
                schema = _openapi_type((media[1] or {}).get("schema")) if media[1] else ""
                responses.append((status, spec.get("description", "") or schema))
            security = "; ".join(sorted((operation.get("security") or [{}])[0].keys())) \
                if operation.get("security") else ""
            returns = next((description for status, description in responses
                            if status.startswith("2")), "")
            operations.append(Operation(
                method=verb.upper(), path=raw_path,
                handler=operation.get("operationId", "") or "—",
                line=0, file=path.as_posix(),
                description=operation.get("summary", "") or operation.get("description", ""),
                params=params, request_body=request_body, returns=returns,
                responses=responses, security=security,
            ))
    operations.sort(key=lambda o: (o.path, o.method))
    title = ((document.get("info") or {}).get("title") or "").strip()
    return operations, title


def _openapi_type(schema) -> str:
    if not isinstance(schema, dict):
        return ""
    if "$ref" in schema:
        return str(schema["$ref"]).rsplit("/", 1)[-1]
    if "type" in schema:
        base = str(schema["type"])
        if base == "array":
            return "List<%s>" % (_openapi_type(schema.get("items")) or "?")
        return base
    if "oneOf" in schema or "anyOf" in schema:
        variants = schema.get("oneOf") or schema.get("anyOf") or []
        return " | ".join(_openapi_type(v) or "?" for v in variants)
    return ""


def sdl_summary(text: str) -> tuple[int, int, int]:
    """(число типов, число полей Query, число полей Mutation) из SDL."""
    types = len(re.findall(r"^\s*(?:type|input|enum|interface|union|scalar)\s+\w+", text, re.M))
    return types, _sdl_field_count(text, "Query"), _sdl_field_count(text, "Mutation")


def _sdl_field_count(text: str, type_name: str) -> int:
    match = re.search(r"^\s*type\s+%s\b[^{]*\{" % type_name, text, re.M)
    if not match:
        return 0
    close = text.find("}", match.end())
    block = text[match.end():close if close > 0 else len(text)]
    return len(re.findall(r"^\s{2,}\w+\s*[(:]", block, re.M))


# ─────────────────────────── конфиг ───────────────────────────

@dataclass
class SurfaceConfig:
    kind: str
    enabled: bool = True
    framework: str = ""
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)


@dataclass
class SourceConfig:
    id: str
    title: str
    root: str
    framework: str = ""
    description: str = ""
    enabled: bool = True
    surfaces: list[SurfaceConfig] = field(default_factory=list)


@dataclass
class Config:
    output_dir: str
    sources: list[SourceConfig]


CONFIG_KEYS = {"version", "output", "source"}
OUTPUT_KEYS = {"dir"}
SOURCE_KEYS = {"id", "title", "root", "framework", "description", "enabled", "surface",
               "include", "exclude", "artifacts"}
SURFACE_KEYS = {"kind", "enabled", "framework", "include", "exclude", "artifacts"}


def check_keys(table: dict, allowed: set[str], where: str) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise SystemExit("api-docs.toml: в [%s] неизвестные ключи: %s"
                         % (where, ", ".join(unknown)))


def load_config(path: Path) -> Config:
    if tomllib is None:
        raise SystemExit("Нужен Python 3.11+ (модуль tomllib) для чтения %s" % path)
    if not path.is_file():
        raise SystemExit("Конфиг %s не найден. Он задаёт правила сбора контрактов API." % path)
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise SystemExit("api-docs.toml: ошибка разбора — %s" % exc)

    check_keys(raw, CONFIG_KEYS, "")
    output = raw.get("output") or {}
    if not isinstance(output, dict):
        raise SystemExit("api-docs.toml: [output] должен быть таблицей")
    check_keys(output, OUTPUT_KEYS, "output")
    output_dir = output.get("dir") or "documentation/api"

    sources: list[SourceConfig] = []
    for index, item in enumerate(raw.get("source") or [], start=1):
        if not isinstance(item, dict):
            raise SystemExit("api-docs.toml: [[source]] #%d должен быть таблицей" % index)
        check_keys(item, SOURCE_KEYS, "source #%d" % index)
        source_id = item.get("id")
        if not source_id:
            raise SystemExit("api-docs.toml: у [[source]] #%d нет обязательного `id`" % index)
        root = item.get("root")
        if not root:
            raise SystemExit("api-docs.toml: у источника `%s` нет обязательного `root`" % source_id)
        source = SourceConfig(
            id=str(source_id),
            title=str(item.get("title") or source_id),
            root=str(root),
            framework=str(item.get("framework") or ""),
            description=str(item.get("description") or ""),
            enabled=bool(item.get("enabled", True)),
        )
        for surface_index, raw_surface in enumerate(item.get("surface") or [], start=1):
            if not isinstance(raw_surface, dict):
                raise SystemExit("api-docs.toml: [[source.surface]] #%d у `%s` должен быть таблицей"
                                 % (surface_index, source_id))
            check_keys(raw_surface, SURFACE_KEYS, "%s.surface #%d" % (source_id, surface_index))
            kind = str(raw_surface.get("kind") or "")
            if kind not in SURFACE_KINDS:
                raise SystemExit("api-docs.toml: у `%s` неизвестная поверхность `%s` (ожидалось: %s)"
                                 % (source_id, kind, ", ".join(SURFACE_KINDS)))
            source.surfaces.append(SurfaceConfig(
                kind=kind,
                enabled=bool(raw_surface.get("enabled", True)),
                framework=str(raw_surface.get("framework") or source.framework or ""),
                include=[str(p) for p in (raw_surface.get("include") or item.get("include") or [])],
                exclude=[str(p) for p in (raw_surface.get("exclude") or item.get("exclude") or [])],
                artifacts=[str(p) for p in (raw_surface.get("artifacts") or [])],
            ))
        sources.append(source)
    if not sources:
        raise SystemExit("api-docs.toml: не описано ни одного [[source]]")
    return Config(output_dir=str(output_dir), sources=sources)


# ─────────────────────────── сбор ───────────────────────────

@dataclass
class Surface:
    kind: str
    source_id: str
    source_title: str
    source_description: str
    mode: str
    origin: str
    resources: list[Resource] = field(default_factory=list)
    gql_fields: list[GqlField] = field(default_factory=list)
    gql_types: list[GqlType] = field(default_factory=list)
    gql_sdl: str = ""
    gql_counts: tuple[int, int, int] = (0, 0, 0)
    proto: list[ProtoDoc] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def contract_count(self) -> int:
        if self.kind == "rest":
            return sum(len(r.operations) for r in self.resources)
        if self.kind == "graphql":
            return len(self.gql_fields) or (self.gql_counts[1] + self.gql_counts[2])
        return sum(len(s.rpcs) for doc in self.proto for s in doc.services)


def glob_files(base: Path, include: list[str], exclude: list[str]) -> list[Path]:
    found: dict[str, Path] = {}
    for pattern in include:
        for path in sorted(base.glob(pattern)):
            if not path.is_file():
                continue
            rel = path.relative_to(base).as_posix()
            if any(fnmatch.fnmatch(rel, ex) or fnmatch.fnmatch(path.name, ex) for ex in exclude):
                continue
            found[rel] = path
    return [found[key] for key in sorted(found)]


def read_sources(root: Path, files: list[Path]) -> list[SourceFile]:
    sources = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            print("⚠ не читается %s: %s" % (path, exc), file=sys.stderr)
            continue
        sources.append(parse_source(path, path.relative_to(root).as_posix(), text))
    return sources


def first_existing(root: Path, names: list[str]) -> Path | None:
    for name in names:
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None


def build_surface(source: SourceConfig, surface: SurfaceConfig, root: Path) -> Surface:
    base = root / source.root
    result = Surface(kind=surface.kind, source_id=source.id, source_title=source.title,
                     source_description=source.description, mode="empty", origin="")
    if not surface.enabled:
        result.mode = "disabled"
        result.origin = "поверхность выключена в `api-docs.toml`"
        return result
    if not base.is_dir():
        result.mode = "empty"
        result.origin = "каталог `%s` не найден" % source.root
        result.warnings.append("%s: каталог `%s` отсутствует" % (source.id, source.root))
        return result

    adapter = ADAPTERS.get((surface.kind, surface.framework.lower()))

    # 1. Готовая спецификация из сборки важнее статического разбора.
    artifact = first_existing(base, surface.artifacts)
    if artifact is not None:
        rel_artifact = artifact.relative_to(root).as_posix()
        try:
            if surface.kind == "rest":
                operations, title = load_openapi(artifact)
                for operation in operations:
                    operation.file = rel_artifact
                resource = Resource(name=(title or source.title), base_path="", line=0,
                                    file=rel_artifact,
                                    description="Спецификация из сборки: `%s`" % rel_artifact)
                resource.operations = operations
                result.resources = [resource] if resource.operations else []
                result.mode = "artifact"
                result.origin = "готовая спецификация OpenAPI из сборки — `%s`" % rel_artifact
                return result
            if surface.kind == "graphql":
                sdl = artifact.read_text(encoding="utf-8")
                result.gql_sdl = sdl
                result.gql_counts = sdl_summary(sdl)
                result.mode = "artifact"
                result.origin = "готовая SDL-схема из сборки — `%s`" % rel_artifact
                return result
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            result.warnings.append("%s: не удалось прочитать `%s` (%s) — падаю на статический разбор"
                                   % (source.id, rel_artifact, exc))

    if adapter is None:
        result.mode = "unsupported"
        result.origin = ("для стека «%s + %s» адаптера пока нет: добавьте его в `ADAPTERS` "
                         "или положите готовую спецификацию в `artifacts`"
                         % (surface.kind, surface.framework or "framework не задан"))
        result.warnings.append("%s/%s: %s" % (source.id, surface.kind, result.origin))
        return result

    files = glob_files(base, surface.include, surface.exclude)
    if not files:
        result.mode = "empty"
        result.origin = "по шаблонам %s в `%s` ничего не нашлось" % (
            ", ".join(code(pattern) for pattern in surface.include) or "—", source.root)
        return result

    rel_files = [path.relative_to(root).as_posix() for path in files]
    if adapter == "proto":
        for path, rel in zip(files, rel_files):
            try:
                result.proto.append(parse_proto(path, rel, path.read_text(encoding="utf-8")))
            except (OSError, UnicodeDecodeError) as exc:
                result.warnings.append("%s: не читается (%s)" % (rel, exc))
        result.mode = "static"
        result.origin = "`.proto` в `%s` — %d %s" % (
            source.root, len(files), plural(len(files), "файл", "файла", "файлов"))
        return result

    if adapter == "contract-yaml":
        for path, rel in zip(files, rel_files):
            try:
                resources, contract_warnings = parse_contract_file(path, rel)
            except (OSError, UnicodeDecodeError, YamlSubsetError) as exc:
                result.warnings.append("%s: не удалось прочитать контракт (%s)" % (rel, exc))
                continue
            result.resources.extend(resources)
            result.warnings.extend(contract_warnings)
        result.mode = "contract" if result.resources else "empty"
        result.origin = "декларативный контракт — %s" % ", ".join(
            code(name) for name in rel_files)
        return result

    sources = read_sources(root, files)
    if surface.kind == "rest":
        resources, warnings = collect_rest(sources)
        result.resources = resources
        result.warnings.extend(warnings)
    else:
        fields, types, warnings = collect_graphql(sources)
        result.gql_fields = fields
        result.gql_types = types
        result.warnings.extend(warnings)
    result.mode = "static"
    result.origin = "код в `%s` — %d %s" % (
        source.root, len(files), plural(len(files), "файл", "файла", "файлов"))
    return result


# ─────────────────────────── рендеринг страниц ───────────────────────────
#
# Страницы читают люди, поэтому сверху — что это и откуда данные, дальше рабочие таблицы,
# а машинные подробности (id рёбер, ограничения разбора) убраны под `<details>`.

GENERATED_NOTE = (
    "_Собрано из кода автоматически: `make api-docs` (в CI — шаг workflow `docs → wiki`). "
    "Править страницу вручную нет смысла — источник правды это код и [`api-docs.toml`](%s)._"
)

SURFACE_ABOUT = {
    "rest": ("Что умеет REST-поверхность: ресурсы, операции, параметры, тела запросов и ответы.",
             "внешние клиенты и интеграции"),
    "graphql": ("Запросы, мутации и типы, на которые они ссылаются.",
                "веб-клиент и клиенты с гибкими выборками"),
    "grpc": ("Сервисы, RPC-методы и сообщения из `.proto`-файлов.",
             "воркеры и внутренние сервисы"),
}

STACK_LABEL = {
    "quarkus": "Quarkus, Kotlin",
    "microprofile-graphql": "MicroProfile GraphQL",
    "jakarta-rest": "Jakarta REST",
    "proto": "protobuf",
    "api-contracts": "декларативный YAML",
}

def blob_url(meta: dict, rel: str, line: int = 0, label: str = "") -> str:
    href = "https://github.com/%s/blob/%s/%s" % (meta["repo"], meta["ref"], quote_path(rel))
    if line:
        href += "#L%d" % line
    return "[`%s`](%s)" % (label or rel, href)


def page_head(title: str, intro: str, meta: dict) -> list[str]:
    config_url = "https://github.com/%s/blob/%s/%s" % (
        meta["repo"], meta["ref"], quote_path(meta["config_rel"]))
    lines = ["# %s" % title, ""]
    if intro:
        lines += [intro.strip(), ""]
    lines += [GENERATED_NOTE % config_url, ""]
    return lines


def table(headers: list[str], rows: list[list[str]]) -> list[str]:
    if not rows:
        return ["_Нет данных._", ""]
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(md_cell(cell) for cell in row) + " |")
    lines.append("")
    return lines


def amounts(count: int, one: str, few: str, many: str) -> str:
    return "%d %s" % (count, plural(count, one, few, many))


def surface_head(surface: Surface, level: str = "##") -> list[str]:
    """Заголовок источника: что за сервис, откуда данные, о чём предупреждаем."""
    lines = ["%s %s" % (level, surface.source_title), ""]
    if surface.source_description:
        lines += [surface.source_description, ""]
    lines += ["_Откуда данные: %s._" % surface.origin, ""]
    for warning in surface.warnings:
        lines += ["> ⚠ %s" % warning, ""]
    return lines


# ── REST ──

def render_rest(surfaces: list[Surface], meta: dict) -> str:
    about, audience = SURFACE_ABOUT["rest"]
    lines = page_head("REST API", "%s Кому: %s." % (about, audience), meta)

    total = sum(surface.contract_count() for surface in surfaces)
    if surfaces:
        parts = ["**%s** — %s" % (surface.source_title,
                                  amounts(surface.contract_count(), "операция", "операции", "операций"))
                 for surface in surfaces]
        lines += ["Всего %s: %s." % (amounts(total, "операция", "операции", "операций"),
                                     ", ".join(parts)), ""]

    for surface in surfaces:
        lines += surface_head(surface)
        if not surface.resources:
            lines += ["Операций здесь нет."
                      + (" Поверхность собирается из декларативного контракта — "
                         "проверьте `paths` в файле." if surface.mode == "contract" else ""), ""]
            continue
        if surface.mode != "artifact":
            lines += ["### Все операции", ""]
            lines += table(["Метод", "Путь", "Что делает"],
                           [[code(op.method), code(op.path), op.description]
                            for resource in surface.resources for op in resource.operations])
        for resource in surface.resources:
            lines += render_rest_resource(resource, meta)

    if not any(surface.contract_count() for surface in surfaces):
        lines += ["_REST-операций не нашлось. Проверьте `include`/`exclude` поверхности в "
                  "`api-docs.toml` и наличие `@Path` в коде._", ""]
    return "\n".join(lines).rstrip() + "\n"


def render_rest_resource(resource: Resource, meta: dict) -> list[str]:
    heading = ("### Эндпоинты" if not resource.base_path
               else "### `%s` — %s" % (resource.name, code(resource.base_path)))
    lines = [heading, ""]
    if resource.description:
        lines += [resource.description, ""]

    facts = []
    if resource.host:
        facts.append(("Хост", code(resource.host)))
    if resource.security:
        facts.append(("Аутентификация", resource.security))
    lines += ["- **%s:** %s" % (label, value) for label, value in facts]
    if facts:
        lines.append("")

    for operation in resource.operations:
        lines += render_operation(operation, meta)
    return lines


def render_operation(operation: Operation, meta: dict) -> list[str]:
    lines = ["#### `%s %s`" % (operation.method, operation.path), ""]
    if operation.description:
        lines += [operation.description, ""]

    facts = []
    if operation.consumes:
        facts.append(("Принимает", code(operation.consumes)))
    if operation.produces:
        facts.append(("Отдаёт", code(operation.produces)))
    if operation.request_body:
        facts.append(("Тело запроса", code(operation.request_body)))
    if operation.returns:
        facts.append(("Возвращает", code(operation.returns)))
    if operation.security:
        facts.append(("Аутентификация", operation.security))
    if operation.responses:
        facts.append(("Ответы", "; ".join(
            "%s — %s" % (code(status), description or "без описания")
            for status, description in operation.responses)))
    if operation.handler and operation.handler != "—" and operation.file:
        facts.append(("Обработчик", blob_url(meta, operation.file, operation.line,
                                             operation.handler)))
    lines += ["- **%s:** %s" % (label, value) for label, value in facts]
    if facts:
        lines.append("")

    params = [param for param in operation.params if param.location != "body"]
    if params:
        lines += table(["Параметр", "Где", "Тип", "Обязательный", "По умолчанию", "Описание"],
                       [[code(param.name), param.location or "—", code(param.type),
                         "да" if param.required else "нет",
                         code(param.default) if param.default else "—", param.description]
                        for param in params])
    return lines


# ── GraphQL ──

def render_graphql(surfaces: list[Surface], meta: dict) -> str:
    about, audience = SURFACE_ABOUT["graphql"]
    lines = page_head("GraphQL API", "%s Кому: %s." % (about, audience), meta)

    for surface in surfaces:
        lines += surface_head(surface)
        if surface.mode == "artifact":
            lines += ["Схема получена целиком из сборки.", ""]
            if surface.gql_sdl:
                lines += ["```graphql", surface.gql_sdl.strip(), "```", ""]
            continue
        if not surface.gql_fields:
            lines += ["Полей `@Query`/`@Mutation` в исходниках нет.", ""]
            continue
        for kind, label, hint in (
            ("query", "Запросы", "Читают данные и ничего не меняют."),
            ("mutation", "Мутации", "Меняют состояние."),
            ("subscription", "Подписки", "Отдают поток событий."),
        ):
            chunk = [field for field in surface.gql_fields if field.kind == kind]
            if not chunk:
                continue
            lines += ["### %s" % label, "", "_%s_" % hint, ""]
            lines += table(["Поле", "Аргументы", "Возвращает", "Описание"],
                           [[code(field.name), gql_args(field), code(field.returns),
                             field.description] for field in chunk])
            for field in chunk:
                lines += render_gql_field(field, meta)
        if surface.gql_types:
            lines += ["### Типы", "",
                      "_Только те, на которые ссылаются запросы и мутации._", ""]
            lines += table(["Тип", "Вид", "Содержимое", "Описание"],
                           [[code(gql_type.name), gql_type.kind,
                             amounts(len(gql_type.fields) or len(gql_type.values),
                                     "поле", "поля", "полей"), gql_type.description]
                            for gql_type in surface.gql_types])
            for gql_type in surface.gql_types:
                lines += render_gql_type(gql_type)

    if not any(surface.gql_fields or surface.gql_sdl for surface in surfaces):
        lines += ["_GraphQL-полей не нашлось: в исходниках нет `@Query`/`@Mutation`, а SDL "
                  "в артефактах сборки отсутствует._", ""]
    return "\n".join(lines).rstrip() + "\n"


def gql_args(field: GqlField) -> str:
    if not field.args:
        return "—"
    return ", ".join("%s: %s" % (arg.name, arg.type)
                     + (" = %s" % arg.default if arg.default else "") for arg in field.args)


def render_gql_field(field: GqlField, meta: dict) -> list[str]:
    lines = ["#### `%s(%s): %s`" % (field.name, gql_args(field) if field.args else "",
                                    field.returns), ""]
    if field.description:
        lines += [field.description, ""]
    if field.args:
        lines += table(["Аргумент", "Тип", "По умолчанию", "Описание"],
                       [[code(arg.name), code(arg.type),
                         code(arg.default) if arg.default else "—", arg.description]
                        for arg in field.args])
    if field.file:
        name = field.file.rsplit("/", 1)[-1]
        label = "%s:%d" % (name, field.line) if field.line else name
        lines += ["_Объявлено: %s_" % blob_url(meta, field.file, field.line, label), ""]
    return lines


def render_gql_type(gql_type: GqlType) -> list[str]:
    lines = ["#### `%s` — %s" % (gql_type.name, gql_type.kind), ""]
    if gql_type.description:
        lines += [gql_type.description, ""]
    if gql_type.values:
        lines += ["Значения: " + ", ".join(code(value) for value in gql_type.values), ""]
    if gql_type.fields:
        lines += table(["Поле", "Тип", "По умолчанию", "Описание"],
                       [[code(field.name), code(field.type),
                         code(field.default) if field.default else "—", field.description]
                        for field in gql_type.fields])
    return lines


# ── gRPC ──

STREAMING_LABEL = {
    "unary": "один запрос → один ответ",
    "server": "server streaming",
    "client": "client streaming",
    "bidi": "bidirectional streaming",
}


def render_grpc(surfaces: list[Surface], meta: dict) -> str:
    about, audience = SURFACE_ABOUT["grpc"]
    lines = page_head("gRPC API", "%s Кому: %s." % (about, audience), meta)

    for surface in surfaces:
        lines += surface_head(surface)
        if not surface.proto:
            lines += ["Здесь пока пусто: `.proto` ещё нет. Положите файлы в каталог, покрытый "
                      "`include` поверхности `grpc` в `api-docs.toml`, и страница соберётся сама.", ""]
            continue
        for document in surface.proto:
            lines += ["### Файл `%s`" % document.rel, ""]
            meta_rows = []
            if document.package:
                meta_rows.append(("Пакет", code(document.package)))
            if document.syntax:
                meta_rows.append(("Синтаксис", code(document.syntax)))
            lines += ["- **%s:** %s" % (label, value) for label, value in meta_rows]
            if meta_rows:
                lines.append("")
            for service in document.services:
                lines += render_service(service)
            if document.messages:
                lines += ["#### Сообщения", ""]
                lines += table(["Сообщение", "Полей", "Описание"],
                               [[code(message.name), str(len(message.fields)), message.description]
                                for message in document.messages])
                for message in document.messages:
                    lines += render_message(message)
            if document.enums:
                lines += ["#### Перечисления", ""]
                for enum in document.enums:
                    lines += render_enum(enum)

    return "\n".join(lines).rstrip() + "\n"


def render_service(service: ProtoService) -> list[str]:
    lines = ["#### Сервис `%s`" % service.name, ""]
    if service.description:
        lines += [service.description, ""]
    if not service.rpcs:
        return lines + ["_Методов не объявлено._", ""]
    lines += table(["Метод", "Тип вызова", "Запрос", "Ответ", "Описание"],
                   [[code(rpc.name), STREAMING_LABEL.get(rpc.streaming, rpc.streaming),
                     code(rpc.request), code(rpc.response), rpc.description]
                    for rpc in service.rpcs])
    return lines


def render_message(message: ProtoMessage) -> list[str]:
    lines = ["##### `%s`" % message.name, ""]
    if message.description:
        lines += [message.description, ""]
    if not message.fields:
        return lines + ["_Полей нет._", ""]
    lines += table(["#", "Поле", "Тип", "Модификатор", "Описание"],
                   [[field.number, code(field.name), code(field.type),
                     field.cardinality or "—", field.description] for field in message.fields])
    return lines


def render_enum(enum: ProtoEnum) -> list[str]:
    lines = ["##### `%s`" % enum.name, ""]
    if enum.description:
        lines += [enum.description, ""]
    lines += table(["Значение", "Номер", "Описание"],
                   [[code(name), number, description] for name, number, description in enum.values])
    return lines


# ── оглавление раздела ──

def render_index(surfaces: dict[str, list[Surface]], config, meta: dict) -> str:
    lines = page_head(
        "API: контракты",
        "Что система обещает клиентам: REST, GraphQL и gRPC. Это снимок кода, а не пожелания — "
        "поэтому страницы не расходятся с реализацией.",
        meta)

    rows = []
    for kind in SURFACE_KINDS:
        about, audience = SURFACE_ABOUT[kind]
        chunk = surfaces.get(kind, [])
        count = sum(surface.contract_count() for surface in chunk)
        if kind == "grpc":
            amount = amounts(count, "метод", "метода", "методов")
        elif kind == "graphql":
            amount = amounts(count, "поле", "поля", "полей")
        else:
            amount = amounts(count, "операция", "операции", "операций")
        rows.append([SURFACE_TITLE[kind], audience, amount if count else "пока пусто",
                     "[открыть](%s)" % SURFACE_PAGE[kind]])
    lines += ["## Поверхности", ""] + table(
        ["Поверхность", "Для кого", "Сколько контрактов", "Страница"], rows)

    source_rows = []
    for source in config.sources:
        kinds = ", ".join(SURFACE_TITLE[kind] for kind in SURFACE_KINDS
                          if any(surface.kind == kind for surface in source.surfaces))
        stack = STACK_LABEL.get(source.framework, source.framework or "—")
        source_rows.append([source.title, code(source.root), stack, kinds or "—",
                            "включён" if source.enabled else "выключен"])
    lines += ["## Источники", ""] + table(
        ["Источник", "Где живёт", "Стек", "Поверхности", "Статус"], source_rows)

    lines += [
        "## Как обновить", "",
        "```bash",
        "make api-docs         # пересобрать страницы контрактов",
        "make api-docs-check   # проверить, что страницы соответствуют коду",
        "```",
        "",
        "В CI отдельная команда не нужна: workflow `docs → wiki` собирает контракты перед "
        "публикацией, поэтому вики всегда отражает текущий коммит.",
        "",
        "## Как расширять", "",
        "- Новый сервис или контейнер — блок `[[source]]` в `api-docs.toml` (`root`, `framework`).",
        "- Новая поверхность у существующего источника — блок `[[source.surface]]` с `kind` "
        "(`rest`, `graphql`, `grpc`) и шаблонами `include`/`exclude`.",
        "- Если у сервиса есть готовая спецификация (OpenAPI в JSON или SDL), укажите её в "
        "`artifacts` — она важнее разбора кода.",
        "- Если кода или аннотаций ещё нет, опишите контракт декларативно: "
        "`framework = \"api-contracts\"` и YAML рядом с сервисом (`host`, `paths`).",
        "",
        "<details>",
        "<summary>Ограничения разбора</summary>",
        "",
        "- Статический разбор читает аннотации и KDoc, но не выполняет код: динамически построенные "
        "пути, унаследованные аннотации и вычисляемые схемы он не увидит.",
        "- Типы приводятся так, как написаны в коде, без нормализации в JSON Schema.",
        "- YAML-спецификации из сборки не читаются (в стандартной библиотеке Python нет YAML-парсера): "
        "REST-артефакт должен быть в JSON. Декларативный YAML-контракт читается подмножеством "
        "парсера — отображения, списки, скаляры и блочные строки; якоря, теги и flow-стиль дают "
        "ошибку с номером строки.",
        "- Страницы не коммитятся в репозиторий: источник правды — код и `api-docs.toml`.",
        "",
        "</details>",
        "",
    ]
    if meta.get("sha"):
        lines += ["_Собрано по коммиту `%s` от %s._" % (meta["sha"], meta["date"] or "—")]
    return "\n".join(lines).rstrip() + "\n"


# ─────────────────────────── сборка и CLI ───────────────────────────

def build(root: Path, config: Config, repo: str, ref: str, config_rel: str,
          dates: bool = True) -> tuple[dict[str, str], list[str]]:
    by_kind: dict[str, list[Surface]] = {kind: [] for kind in SURFACE_KINDS}
    warnings: list[str] = []
    for source in config.sources:
        if not source.enabled:
            continue
        for surface_config in source.surfaces:
            surface = build_surface(source, surface_config, root)
            by_kind[surface_config.kind].append(surface)
            warnings.extend(surface.warnings)
    sha, date = commit_info(root) if dates else ("", "")
    meta = {"repo": repo, "ref": ref, "sha": sha, "date": date, "config_rel": config_rel}

    pages = {
        INDEX_PAGE: render_index(by_kind, config, meta),
        SURFACE_PAGE["rest"]: render_rest(by_kind["rest"], meta),
        SURFACE_PAGE["graphql"]: render_graphql(by_kind["graphql"], meta),
        SURFACE_PAGE["grpc"]: render_grpc(by_kind["grpc"], meta),
    }
    return pages, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Контракты REST/GraphQL/gRPC из кода → документация API")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="путь к api-docs.toml")
    parser.add_argument("--root", default=".", help="корень репозитория")
    parser.add_argument("--out", help="переопределить каталог вывода из [output].dir")
    parser.add_argument("--check", action="store_true",
                        help="не писать файлы, а проверить, что они соответствуют коду")
    parser.add_argument("--no-dates", action="store_true", help="не ходить в git за датой коммита")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPO),
                        help="репозиторий для ссылок на исходники (по умолчанию из GITHUB_REPOSITORY)")
    parser.add_argument("--ref", default=os.environ.get("GITHUB_REF_NAME", DEFAULT_REF),
                        help="ветка/тег для ссылок на исходники (по умолчанию из GITHUB_REF_NAME)")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = root / config_path
    try:
        config_rel = config_path.relative_to(root).as_posix()
    except ValueError:
        config_rel = config_path.name

    config = load_config(config_path)
    out_dir = Path(args.out) if args.out else root / config.output_dir

    pages, warnings = build(root, config, args.repo, args.ref, config_rel,
                            dates=not args.no_dates)
    for warning in dict.fromkeys(warnings):
        print("⚠ %s" % warning, file=sys.stderr)

    if args.check:
        stale = []
        for name, content in pages.items():
            target = out_dir / name
            if not target.is_file() or target.read_text(encoding="utf-8") != content:
                stale.append(name)
        if stale:
            print("Страницы не соответствуют коду: %s" % ", ".join(sorted(stale)))
            print("Пересоберите: make api-docs")
            return 1
        print("Контракты актуальны: %d %s в %s"
              % (len(pages), plural(len(pages), "страница", "страницы", "страниц"), out_dir))
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    for name, content in pages.items():
        (out_dir / name).write_text(content, encoding="utf-8")
    print("Записано %d %s в %s: %s"
          % (len(pages), plural(len(pages), "страница", "страницы", "страниц"), out_dir,
             ", ".join(sorted(pages))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
