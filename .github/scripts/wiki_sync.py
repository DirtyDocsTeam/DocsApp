#!/usr/bin/env python3
"""Синхронизация documentation/ репозитория в GitHub Wiki.

Что делает:
  * documentation/**/*.md            → страницы вики (путь `a/b.md` → страница `a--b`), текст дословно,
                              но относительные ссылки переписываются (md → ссылка на страницу вики,
                              картинки → raw-URL для встраивания, прочие файлы → blob-URL);
  * documentation/**/<артефакт>      → встраиваются картинкой, если формат отображаемый, иначе ссылкой;
                              не упомянутые в тексте артефакты попадают в авто-блок «Файлы в этой папке»
                              и на страницу Artifacts;
  * Home.md, _Sidebar.md, _Footer.md, Artifacts.md — генерируются целиком (описание проекта, гайд,
                              индекс страниц с датами последних коммитов, инвентарь артефактов).

Всё, что сгенерировано, помечается MARKER-комментарием: страницы без маркера не трогаются,
устаревшие страницы с маркером удаляются.

Использование:
  python3 .github/scripts/wiki_sync.py --wiki /tmp/wiki        # локальная папка вместо клона
  python3 .github/scripts/wiki_sync.py --dry-run --out /tmp/out
  WIKI_TOKEN=... python3 .github/scripts/wiki_sync.py          # клонировать вики и запушить
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

# ─────────────────────────── константы ───────────────────────────

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".avif"}
DRAWIO_EXT = {".drawio", ".dio"}
OTHER_VIEWABLE_EXT = {".pdf"}
MARKER_TOKEN = "wiki-sync:managed"
MARKER = "<!-- " + MARKER_TOKEN + " · файл генерируется из documentation/, правки в вики перезапишутся -->"

HOME_FILE = "Home.md"
ARTIFACTS_FILE = "Artifacts.md"
SIDEBAR_FILE = "_Sidebar.md"
FOOTER_FILE = "_Footer.md"
GENERATED_FIXED = {HOME_FILE, ARTIFACTS_FILE, SIDEBAR_FILE, FOOTER_FILE}

# страницы, которые используются как источник описания, но не публикуются отдельно
INTRO_SOURCES = ("README.md", "index.md")

DESCRIPTION = (
    "DocsApp — сервис оформления документов по **ГОСТ 7.32-2017**: Markdown/шаблон → DOCX/PDF/ODT "
    "с библиотекой стилей и тем, валидацией оформления и публичным API. "
    "Репозиторий: [DirtyDocsTeam/DocsApp](https://github.com/DirtyDocsTeam/DocsApp)."
)

TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z",
    "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


# ─────────────────────────── утилиты ───────────────────────────

def slug(text: str) -> str:
    out = []
    for ch in text.lower():
        if ch.isascii() and (ch.isalnum() or ch in "-_."):
            out.append(ch)
        elif ch in TRANSLIT:
            out.append(TRANSLIT[ch])
        elif ch in " \t":
            out.append("-")
        else:
            out.append("-")
    s = re.sub(r"-{2,}", "-", "".join(out)).strip("-._")
    return s or "page"


def plural(n: int, one: str, few: str, many: str) -> str:
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return one
    if 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        return few
    return many


def is_drawio_preview(p: Path) -> bool:
    """`arch.png` рядом с `arch.drawio` — предпросмотр, отдельной строкой в инвентаре не нужен."""
    return p.suffix.lower() in {".png", ".svg"} and p.with_suffix(".drawio").exists()


def human_size(n: int) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if n < 1024 or unit == "ГБ":
            return ("%d %s" % (n, unit)) if unit == "Б" else ("%.1f %s" % (n, unit))
        n /= 1024.0
    return "%d Б" % n


def quote_path(path: str) -> str:
    return urllib.parse.quote(path, safe="/")


def git(*args: str, cwd: Path | None = None) -> str:
    res = subprocess.run(["git", *args], cwd=str(cwd) if cwd else None,
                         capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError("git %s: %s" % (" ".join(args), res.stderr.strip()))
    return res.stdout


def read_ignore(docs: Path) -> list[str]:
    """documentation/.wikiignore — по одному fnmatch-шаблону на строку (как .gitignore, но проще)."""
    p = docs / ".wikiignore"
    if not p.exists():
        return []
    return [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")]


# ─────────────────────────── модель документации ───────────────────────────

class Docs:
    def __init__(self, root: Path, repo: str, ref: str, log_dates: bool = True):
        self.root = root
        self.docs = root / "documentation"
        self.repo = repo
        self.ref = ref
        self._date_cache: dict[str, str] = {}
        self.use_git = log_dates
        self.ignore = read_ignore(self.docs)

    # --- пути и URL ---
    def rel(self, p: Path) -> str:
        return p.relative_to(self.root).as_posix()

    def raw_url(self, p: Path) -> str:
        return "https://raw.githubusercontent.com/%s/%s/%s" % (self.repo, self.ref, quote_path(self.rel(p)))

    def blob_url(self, p: Path) -> str:
        return "https://github.com/%s/blob/%s/%s" % (self.repo, self.ref, quote_path(self.rel(p)))

    def drawio_url(self, p: Path) -> str:
        return "https://app.diagrams.net/?url=" + urllib.parse.quote(self.raw_url(p), safe="")

    def commit_date(self) -> str:
        """Дата коммита, из которого собрана вики: стабильна для одного коммита, не «сегодня»."""
        if "_commit_date" not in self.__dict__:
            date = ""
            if self.use_git:
                try:
                    date = git("log", "-1", "--format=%cs", cwd=self.root).strip()
                except (RuntimeError, FileNotFoundError):
                    date = ""
            self._commit_date = date
        return self._commit_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def last_commit_date(self, p: Path) -> str:
        if not self.use_git:
            return ""
        key = self.rel(p)
        if key not in self._date_cache:
            try:
                out = git("log", "-1", "--format=%cs", "--", key, cwd=self.root).strip()
            except (RuntimeError, FileNotFoundError):
                out = ""
            self._date_cache[key] = out
        return self._date_cache[key]

    # --- обход файлов ---
    def ignored(self, p: Path) -> bool:
        relp = p.relative_to(self.docs).as_posix()
        return any(fnmatch.fnmatch(relp, pat) or fnmatch.fnmatch(p.name, pat) for pat in self.ignore)

    def files(self) -> tuple[list[Path], list[Path]]:
        md, artifacts = [], []
        for p in sorted(self.docs.rglob("*")):
            if not p.is_file() or self.ignored(p) or p.name.startswith("."):
                continue
            (md if p.suffix.lower() == ".md" else artifacts).append(p)
        return md, artifacts

    # --- имена страниц ---
    def page_name(self, p: Path) -> str:
        """documentation/a/b.md → `a--b`; documentation/a/README.md (или index.md) → `a` — страница-описание раздела."""
        rel = p.relative_to(self.docs).with_suffix("")
        parts = list(rel.parts)
        if len(parts) > 1 and parts[-1].lower() in {"readme", "index"}:
            parts = parts[:-1]
        return "--".join(slug(part) for part in parts)

    def intro_source(self, md: list[Path]) -> Path | None:
        for name in INTRO_SOURCES:
            cand = self.docs / name
            if cand in md:
                return cand
        return None


# ─────────────────────────── рендер артефактов ───────────────────────────

def artifact_md(docs: Docs, p: Path) -> str:
    """Строка авто-перечисления: всегда ссылка, без встраивания содержимого."""
    name = p.name
    ext = p.suffix.lower()
    size = human_size(p.stat().st_size)
    blob = docs.blob_url(p)

    if ext in DRAWIO_EXT:
        return "- [%s](%s) — исходник draw.io (%s) · [открыть в diagrams.net](%s)" % (
            name, blob, size, docs.drawio_url(p))
    if ext in OTHER_VIEWABLE_EXT:
        return "- [%s](%s) — PDF (%s), открывается в браузере" % (name, blob, size)
    if ext in IMAGE_EXT:
        return "- [%s](%s) — изображение (%s)" % (name, blob, size)
    return "- [%s](%s) — файл (%s)" % (name, blob, size)


# ─────────────────────────── переписывание ссылок ───────────────────────────

LINK_RE = re.compile(r"(!?)\[([^\]]*)\]\(\s*<?([^)\s<>]+)>?(\s+\"[^\"]*\")?\s*\)")


def rewrite_links(docs: Docs, page: Path, text: str, page_of: dict[Path, str]) -> tuple[str, set[str]]:
    """Относительные ссылки → ссылки вики / raw / blob. Возвращает текст и упомянутые файлы."""
    mentioned: set[str] = set()

    def repl(m: re.Match) -> str:
        bang, label, url, title = m.group(1), m.group(2), m.group(3), m.group(4) or ""
        if re.match(r"^(https?:|mailto:|tel:|#|data:)", url) or url.startswith("//"):
            return m.group(0)
        anchor = ""
        target = url
        if "#" in target:
            target, anchor = target.split("#", 1)
            anchor = "#" + anchor
        if not target:
            return m.group(0)
        resolved = (page.parent / target).resolve()
        try:
            resolved.relative_to(docs.root)
        except ValueError:
            return m.group(0)
        if not resolved.exists():
            return m.group(0)
        mentioned.add(resolved.as_posix())
        ext = resolved.suffix.lower()

        if ext == ".md":
            name = page_of.get(resolved)
            if name:
                return "%s[%s](%s%s)" % (bang, label, name, anchor)
            return "%s[%s](%s%s)" % (bang, label, docs.blob_url(resolved), anchor)
        if ext in IMAGE_EXT:
            return "%s[%s](%s)%s" % ("!" if bang else "", label, docs.raw_url(resolved), title)
        if ext in DRAWIO_EXT and bang:
            # image-синтаксис для .drawio невозможен: даём ссылку + предпросмотр, если он есть
            sibling = resolved.with_suffix(".png")
            if not sibling.exists():
                sibling = resolved.with_suffix(".svg")
            parts = []
            if sibling.exists():
                parts.append("![%s](%s)" % (label or sibling.name, docs.raw_url(sibling)))
            parts.append("[%s](%s) · [открыть в diagrams.net](%s)" % (
                label or resolved.name, docs.blob_url(resolved), docs.drawio_url(resolved)))
            return "\n\n".join(parts)
        return "%s[%s](%s%s)%s" % (bang, label, docs.blob_url(resolved), anchor, title)

    return LINK_RE.sub(repl, text), mentioned


def strip_h1(text: str) -> tuple[str, str]:
    lines = text.lstrip("\n").splitlines()
    title = ""
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip()
        lines = lines[1:]
    while lines and not lines[0].strip():
        lines = lines[1:]
    return title, "\n".join(lines)


# ─────────────────────────── генерация вики ───────────────────────────

def guide_md() -> str:
    return """## Как добавить страницу

1. Положите файл `documentation/<раздел>/<имя>.md` и запушьте в `main` — вики обновится сама (workflow `docs → wiki`).
2. Первая строка — заголовок `# Название страницы`, дальше обычный Markdown.
3. Имя файла — латиница, цифры, дефисы: `documentation/research/docx-style-extraction.md`.
   Имя страницы в вики получается из пути: `documentation/research/docx-style-extraction.md` → `research--docx-style-extraction`
   (раздел и имя соединяются `--`, вложенность растёт так же: `a/b/c.md` → `a--b--c`).
4. Ссылки на соседние страницы пишите **относительными** — `[отчёт](../research/docx-style-extraction.md)`
   или `[отчёт](docx-style-extraction.md)`: при синке они превращаются в ссылки вики.
5. Внешние ссылки (`https://…`) и `#anchor` остаются как есть.
6. Нужна страница-описание раздела — заведите `documentation/<раздел>/README.md` (или `index.md`): она
   опубликуется как страница с именем раздела (`documentation/research/README.md` → `research`) и встанет первой в навигации.
7. Страницы из вики править бесполезно — они перезаписываются из `documentation/`. Источник правды — репозиторий.

## Как добавить артефакт (картинка, диаграмма, файл)

1. Кладите файл в ту же папку `documentation/…`, имя — латиница/цифры/дефисы (`documentation/research/erd.svg`).
2. Ссылайтесь на него из md относительным путём — тогда он появится там, где нужно:
   `![ERD](erd.svg)` или `[Пояснение](poc/notes.pdf)`.
3. Как это отображается в вики:

| Формат | Что делает синк |
|---|---|
| `.png .jpg .jpeg .gif .webp .svg .bmp .avif` | ссылка на файл; встроить картинку можно только явно — `![подпись](erd.svg)` в тексте страницы |
| `.drawio` / `.dio` | ссылка на исходник + «открыть в diagrams.net» |
| `.pdf` | ссылка (GitHub показывает PDF в браузере) |
| всё остальное (`.docx .zip .xlsx .py .sql` …) | ссылка на файл в репозитории |

4. Файл, на который никто не сослался, всё равно попадёт в вики: в авто-блок **«Файлы в этой папке»**
   под страницей раздела и в общий инвентарь **[Artifacts](Artifacts)** — в обоих местах он показан
   ссылкой, без встраивания.
5. Предпросмотр для `.drawio` делается экспортом: `drawio --export --format png documentation/x.drawio`.
   Чтобы картинка появилась на странице, сослайтесь на неё в тексте: `![Схема](x.png)`.
6. Ограничения: файлы больше ~50 МБ в git не кладём (для тяжёлых — release assets или S3 и обычная ссылка);
   секреты, токены и персональные данные в `documentation/` не коммитим.

## Как это работает

| Что | Откуда | Где в вики |
|---|---|---|
| Страницы | `documentation/**/*.md` | по одной странице на файл, ссылки переписаны под вики |
| Артефакты | все файлы `documentation/**`, кроме `.md` | ссылки в авто-блоке и в `Artifacts`; картинка встраивается только явной ссылкой `![]()` |
| Главная и навигация | генерируются | `Home`, `_Sidebar`, `_Footer`, `Artifacts` |
| Описание проекта | `documentation/README.md` (если есть), иначе встроенный текст | блок «О проекте» на главной |

Сгенерированные страницы помечены комментарием `wiki-sync:managed`: их перезаписывает workflow,
а страницы, удалённые из `documentation/`, из вики вычищаются. Страницы, созданные руками (без пометки), не трогаются.
Исключить файл/папку из синка можно строкой-шаблоном в `documentation/.wikiignore`
(например `poc/*` или `*.draft.md`).
"""


def build(docs: Docs) -> dict[str, str]:
    md_files, artifacts = docs.files()
    intro = docs.intro_source(md_files)
    published = [p for p in md_files if p != intro]

    page_of: dict[Path, str] = {}
    used: set[str] = set()
    for p in published:
        name = docs.page_name(p)
        base, i = name, 2
        while name in used or name.lower() in {f.lower() for f in GENERATED_FIXED}:
            name = "%s-%d" % (base, i)
            i += 1
        used.add(name)
        page_of[p.resolve()] = name
    if intro:
        page_of[intro.resolve()] = HOME_FILE[:-3]

    listed = [a for a in artifacts if not is_drawio_preview(a)]

    pages: dict[str, str] = {}
    for p in published:
        name = page_of[p.resolve()]
        body, mentioned = rewrite_links(docs, p, p.read_text(encoding="utf-8"), page_of)
        footer = artifacts_footer(docs, p, listed, mentioned)
        text = body.rstrip() + ("\n" + footer if footer else "")
        pages[name + ".md"] = text.rstrip() + "\n\n" + MARKER + "\n"

    pages[HOME_FILE] = home_md(docs, published, page_of, listed, intro) + "\n" + MARKER + "\n"
    pages[ARTIFACTS_FILE] = artifacts_md(docs, listed) + "\n" + MARKER + "\n"
    pages[SIDEBAR_FILE] = sidebar_md(docs, published, page_of) + "\n" + MARKER + "\n"
    pages[FOOTER_FILE] = footer_page_md(docs) + "\n" + MARKER + "\n"
    return pages


def artifacts_footer(docs: Docs, page: Path, artifacts: list[Path], mentioned: set[str]) -> str:
    folder = page.parent
    local = [a for a in artifacts
             if folder in a.parents and a.as_posix() not in mentioned]
    if not local:
        return ""
    lines = ["", "---", "", '<a id="files"></a>', "", "### Файлы в этой папке", "",
             "_Сгенерировано автоматически: артефакты рядом со страницей, на которые в тексте нет ссылки._", ""]
    for a in sorted(local):
        lines.append(artifact_md(docs, a))
        lines.append("")
    return "\n".join(lines)


def page_title(text: str, fallback: str) -> str:
    title, _ = strip_h1(text)
    return title or fallback


def home_md(docs: Docs, published: list[Path], page_of: dict[Path, str],
            artifacts: list[Path], intro: Path | None) -> str:
    if intro:
        _, intro_body = strip_h1(intro.read_text(encoding="utf-8"))
        # README уходит на Home как есть: относительные ссылки нужно переписать и здесь,
        # иначе в вики они ведут на несуществующие адреса
        intro_body, _ = rewrite_links(docs, intro, intro_body, page_of)
    else:
        intro_body = DESCRIPTION

    rows = []
    for p in published:
        rel = p.relative_to(docs.docs)
        section = rel.parts[0] if len(rel.parts) > 1 else "—"
        title = page_title(p.read_text(encoding="utf-8"), p.stem)
        rows.append("| [%s](%s) | `%s` | %s |" % (title, page_of[p.resolve()], rel.as_posix(),
                                                  docs.last_commit_date(p) or "—"))

    by_kind = {"картинки": 0, "drawio": 0, "pdf": 0, "прочее": 0}
    for a in artifacts:
        ext = a.suffix.lower()
        by_kind["картинки" if ext in IMAGE_EXT else "drawio" if ext in DRAWIO_EXT
                else "pdf" if ext in OTHER_VIEWABLE_EXT else "прочее"] += 1
    kinds = ", ".join("%s: %d" % (k, v) for k, v in by_kind.items() if v)

    return "\n".join([
        "# DocsApp — документация",
        "",
        intro_body.strip(),
        "",
        "## Разделы",
        "",
        "| Страница | Файл в репозитории | Обновлено |",
        "|---|---|---|",
        *(rows or ["| _пока нет страниц_ | — | — |"]),
        "",
        "## Артефакты",
        "",
        "Всего файлов вне Markdown: **%d**%s. Полный инвентарь со встроенными картинками и ссылками — "
        "страница **[Artifacts](Artifacts)**." % (
            len(artifacts), (" (%s)" % kinds) if kinds else ""),
        "",
        "## Быстрые ссылки",
        "",
        "- [Репозиторий](https://github.com/%s) · [Issues](https://github.com/%s/issues)" % (docs.repo, docs.repo),
        "- [Все артефакты](Artifacts) · [documentation/ в репозитории](https://github.com/%s/tree/%s/documentation)" % (docs.repo, docs.ref),
        "",
        guide_md(),
        "",
        "---",
        "",
        "_Главная сгенерирована автоматически из `documentation/`. Описание проекта берётся из `documentation/README.md`._",
    ])


def artifacts_md(docs: Docs, artifacts: list[Path]) -> str:
    if not artifacts:
        return "# Артефакты\n\n_В `documentation/` пока нет файлов, кроме Markdown._"
    groups: dict[str, list[Path]] = {}
    for a in artifacts:
        group = a.parent.relative_to(docs.docs).as_posix()
        groups.setdefault("documentation/" if group == "." else "documentation/" + group + "/", []).append(a)

    total = sum(a.stat().st_size for a in artifacts)
    lines = ["# Артефакты", "",
             "Инвентарь файлов из `documentation/` (всё, что не `.md`): только ссылки на файлы в репозитории, "
             "без встраивания. Всего **%d** %s, %s." % (
                 len(artifacts), plural(len(artifacts), "файл", "файла", "файлов"), human_size(total)), "",
             "Как добавить свой артефакт — в разделе [«Как добавить артефакт»](Home#как-добавить-артефакт-картинка-диаграмма-файл) "
             "на главной.", ""]
    for group in sorted(groups):
        lines += ["## `%s`" % group, ""]
        for a in groups[group]:
            lines += [artifact_md(docs, a), ""]
    return "\n".join(lines).rstrip()


SIDEBAR_TITLE_MAX = 64


def short_title(text: str, fallback: str) -> str:
    """Подпись для навигации: без ссылки на issue и без длинных хвостов."""
    title = re.sub(r"\s*\((?:issue\s*)?#?\d+\)\s*$", "", page_title(text, fallback), flags=re.I)
    title = re.sub(r"\s+", " ", title).strip() or fallback
    if len(title) > SIDEBAR_TITLE_MAX:
        cut = title[:SIDEBAR_TITLE_MAX].rsplit(" ", 1)[0] or title[:SIDEBAR_TITLE_MAX]
        title = cut.rstrip(" ,.;:—-") + "…"
    return title


def sidebar_md(docs: Docs, published: list[Path], page_of: dict[Path, str]) -> str:
    """Навигация: служебные страницы строкой, дальше разделы.

    Заголовок раздела — это его лендинг (`<раздел>/README.md`), поэтому он же служит ссылкой
    на страницу раздела и не дублируется пунктом ниже. Разделы без страниц (только лендинг)
    уходят в конец, чтобы не раздувать навигацию пустыми блоками.
    """
    top: list[tuple[str, str]] = []
    sections: dict[str, list[Path]] = {}
    for p in published:
        parts = p.relative_to(docs.docs).parts
        if len(parts) > 1:
            sections.setdefault(parts[0], []).append(p)
        else:
            top.append((short_title(p.read_text(encoding="utf-8"), p.stem), page_of[p.resolve()]))

    links = ["[Артефакты](Artifacts)"]
    links += ["[%s](%s)" % (title, page) for title, page in sorted(top, key=lambda item: item[1])]
    lines = ["**[DocsApp](Home)**", "", " · ".join(links), ""]

    def split_section(section: str) -> tuple[Path | None, list[Path]]:
        landing = slug(section)
        landing_page = next((p for p in sections[section] if page_of[p.resolve()] == landing), None)
        rest = [p for p in sections[section] if p is not landing_page]
        return landing_page, rest

    def section_order(section: str) -> tuple[bool, str]:
        return (not split_section(section)[1], section)

    for section in sorted(sections, key=section_order):
        landing_page, rest = split_section(section)
        if landing_page:
            title = short_title(landing_page.read_text(encoding="utf-8"), section)
            lines.append("**[%s](%s)**" % (title, slug(section)))
        else:
            lines.append("**%s**" % section.replace("-", " ").replace("_", " ").capitalize())
        lines.append("")
        for p in sorted(rest, key=lambda q: page_of[q.resolve()]):
            lines.append("- [%s](%s)" % (short_title(p.read_text(encoding="utf-8"), p.stem),
                                         page_of[p.resolve()]))
        if rest:
            lines.append("")
    return "\n".join(lines).rstrip()


def footer_page_md(docs: Docs) -> str:
    return ("Документация синхронизируется из [`documentation/`](https://github.com/%s/tree/%s/documentation) · "
            "сборка по коммиту от %s · править нужно в репозитории, правки в вики перезапишутся."
            % (docs.repo, docs.ref, docs.commit_date()))


# ─────────────────────── применение к вики ───────────────────────

def write_pages(target: Path, pages: dict[str, str]) -> list[str]:
    removed = []
    for existing in sorted(target.glob("*.md")):
        if existing.name in pages:
            continue
        if MARKER_TOKEN in existing.read_text(encoding="utf-8", errors="replace"):
            existing.unlink()
            removed.append(existing.name)
    for name, content in pages.items():
        (target / name).write_text(content, encoding="utf-8")
    return removed


def clone_wiki(repo: str, token: str, dest: Path) -> None:
    url = "https://x-access-token:%s@github.com/%s.wiki.git" % (token, repo)
    res = subprocess.run(["git", "clone", "--depth", "1", url, str(dest)],
                         capture_output=True, text=True)
    if res.returncode != 0:
        sys.stderr.write(
            "Не удалось склонировать %s.wiki.git.\n"
            "Проверьте: (1) в репозитории включён Wiki, (2) в нём создана хотя бы одна страница "
            "через UI (иначе git-репозиторий вики ещё не существует), (3) у секрета WIKI_TOKEN есть "
            "право писать в вики (классический PAT со scope `repo`).\n"
            "git: %s\n" % (repo, res.stderr.strip()))
        raise SystemExit(1)


def main() -> int:
    ap = argparse.ArgumentParser(description="documentation/ → GitHub Wiki")
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "DirtyDocsTeam/DocsApp"))
    ap.add_argument("--ref", default=os.environ.get("GITHUB_REF_NAME", "main"))
    ap.add_argument("--root", default=".", help="корень репозитория (в нём должна быть documentation/)")
    ap.add_argument("--wiki", help="локальная папка вики вместо клонирования (для отладки)")
    ap.add_argument("--out", help="записать результат в пустую папку, ничего не пушить (dry-run)")
    ap.add_argument("--push", action="store_true", help="закоммитить и запушить изменения в вики")
    ap.add_argument("--no-dates", action="store_true", help="не ходить в git log за датами страниц")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not (root / "documentation").is_dir():
        print("documentation/ не найдена в %s — синхронизировать нечего." % root)
        return 0

    docs = Docs(root, args.repo, args.ref, log_dates=not args.no_dates)
    pages = build(docs)
    print("Страниц к публикации: %d (%s)" % (len(pages), ", ".join(sorted(pages))))

    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        for name, content in pages.items():
            (out / name).write_text(content, encoding="utf-8")
        print("Записано в %s" % out)
        return 0

    tmp = None
    try:
        if args.wiki:
            target = Path(args.wiki)
        else:
            token = os.environ.get("WIKI_TOKEN", "")
            if not token:
                sys.stderr.write("Не задан WIKI_TOKEN (PAT со scope `repo`) — пушить в вики нечем.\n")
                return 1
            tmp = Path(tempfile.mkdtemp(prefix="wiki-"))
            target = tmp / "wiki"
            clone_wiki(args.repo, token, target)
        removed = write_pages(target, pages)
        if removed:
            print("Удалено устаревших страниц: %s" % ", ".join(removed))
        if args.wiki and not args.push:
            print("Записано в %s (--push не задан, коммит не делаем)." % target)
            return 0
        git("add", "-A", cwd=target)
        if not git("status", "--porcelain", cwd=target).strip():
            print("Вики уже актуальна — коммит не нужен.")
            return 0
        git("-c", "user.name=github-actions[bot]",
            "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
            "commit", "-m", "docs: синхронизация wiki из %s@%s" % (args.repo, args.ref[:7]), cwd=target)
        git("push", "origin", "HEAD", cwd=target)
        print("Вики обновлена.")
        return 0
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
