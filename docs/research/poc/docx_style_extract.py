#!/usr/bin/env python3
"""PoC к issue #8: извлечение стилей из .docx (OOXML) в нормализованный JSON.

Только stdlib (zipfile + xml.etree) - чтобы показать, что базовая выжимка
стилей не требует тяжёлых зависимостей и работает на любом стеке.

Что делает:
  * читает OPC-контейнер (zip): styles.xml, theme1.xml, numbering.xml,
    document.xml, settings.xml, docProps/*;
  * нормализует единицы (half-point -> pt, dxa -> мм) и разыменовывает
    theme-ссылки на шрифты (asciiTheme="minorHAnsi" -> реальный typeface);
  * строит список стилей + "эффективный" стиль (docDefaults -> basedOn-цепочка
    -> собственные свойства), т.е. то, что реально видит рендерер;
  * считает статистику прямого форматирования в теле документа - главный
    индикатор того, ловится ли оформление стилями или "ручками";
  * собирает список необработанных элементов (coverage), чтобы честно
    показать границы PoC.

Использование:
    python3 docx_style_extract.py file.docx [-o out.json] [--no-effective]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import signal
import sys
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
W = f"{{{W_NS}}}"
A = f"{{{A_NS}}}"

TWIP_MM = 25.4 / 1440.0  # 1 dxa = 1/20 pt = 1/1440 дюйма

# Какие свойства rPr/pPr мы сознательно нормализуем. Всё остальное попадает
# в "unsupported" - это и есть заявленное покрытие PoC.
RPR_KNOWN = {
    "rFonts", "sz", "szCs", "b", "bCs", "i", "iCs", "caps", "smallCaps", "strike",
    "dstrike", "u", "color", "highlight", "vertAlign", "spacing", "kern",
    "position", "lang", "rStyle", "noProof", "vanish", "webHidden", "rtl",
    "em", "shd", "bdr", "snapToGrid", "specVanish", "oMath", "w", "effect",
    "outline", "shadow", "imprint",
}
PPR_KNOWN = {
    "pStyle", "jc", "ind", "spacing", "keepNext", "keepLines", "pageBreakBefore",
    "widowControl", "contextualSpacing", "outlineLvl", "numPr", "tabs", "rPr",
    "sectPr", "pBdr", "shd", "snapToGrid", "autoSpaceDE", "autoSpaceDN",
    "textAlignment", "textDirection", "bidi", "adjustRightInd", "wordWrap",
    "suppressLineNumbers", "framePr", "mirrorIndents", "punctuationKerning",
    "overflowPunct", "topLinePunct", "kinsoku", "textboxTightWrap", "divId",
    "cnfStyle", "textAlignment",
}

# Часто встречающиеся таблицы уровней нумерации для ГОСТ-подобных списков.
NUMFMT_HUMAN = {
    "decimal": "1, 2, 3", "lowerLetter": "а, б, в", "upperLetter": "А, Б, В",
    "lowerRoman": "i, ii, iii", "upperRoman": "I, II, III",
    "bullet": "•", "none": "(без номера)", "decimalZero": "01, 02",
    "russianLower": "а, б, в", "russianUpper": "А, Б, В",
}


# ---------------------------------------------------------------- утилиты ---
def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def on_off(el: ET.Element | None, default: bool | None = None):
    """w:b / w:b w:val="0" / w:b w:val="off" -> True/False/None."""
    if el is None:
        return default
    val = el.get(f"{W}val")
    if val is None:
        return True
    return val.lower() not in ("0", "false", "off")


def val(el: ET.Element | None, name: str = "val", default=None):
    if el is None:
        return default
    return el.get(f"{W}{name}", default)


def pt_from_halfpoints(raw) -> float | None:
    return None if raw is None else round(int(raw) / 2.0, 2)


def mm_from_twips(raw) -> float | None:
    return None if raw is None else round(int(raw) * TWIP_MM, 2)


def pt_from_twips(raw) -> float | None:
    return None if raw is None else round(int(raw) / 20.0, 2)


# ------------------------------------------------------------------- rPr ---
def parse_rfonts(el: ET.Element) -> dict:
    out = {}
    for key, attr in (
        ("ascii", "ascii"), ("hAnsi", "hAnsi"), ("eastAsia", "eastAsia"), ("cs", "cs"),
    ):
        if el.get(f"{W}{attr}"):
            out[key] = el.get(f"{W}{attr}")
    for key, attr in (
        ("ascii", "asciiTheme"), ("hAnsi", "hAnsiTheme"),
        ("eastAsia", "eastAsiaTheme"), ("cs", "cstheme"),
    ):
        if el.get(f"{W}{attr}"):
            out[f"{key}Theme"] = el.get(f"{W}{attr}")
    if el.get(f"{W}hint"):
        out["hint"] = el.get(f"{W}hint")
    return out


def parse_rpr(el: ET.Element | None, unknown: Counter | None = None) -> dict:
    if el is None:
        return {}
    out: dict = {}
    for child in el:
        tag = local(child.tag)
        if unknown is not None and tag not in RPR_KNOWN:
            unknown[tag] += 1
        if tag == "rFonts":
            out["font"] = parse_rfonts(child)
        elif tag == "sz":
            out["sizePt"] = pt_from_halfpoints(val(child))
        elif tag == "szCs":
            out["sizeCsPt"] = pt_from_halfpoints(val(child))
        elif tag in ("b", "bCs", "i", "iCs", "caps", "smallCaps", "strike",
                     "dstrike", "vanish", "noProof", "webHidden", "rtl", "outline",
                     "shadow", "imprint", "em", "snapToGrid"):
            key = {"b": "bold", "i": "italic", "bCs": "boldCs", "iCs": "italicCs",
                   "smallCaps": "smallCaps", "caps": "caps"}.get(tag, tag)
            out[key] = on_off(child)
        elif tag == "u":
            out["underline"] = {"type": val(child) or "single", "color": val(child, "color")}
        elif tag == "color":
            out["color"] = {"hex": val(child), "themeColor": val(child, "themeColor"),
                            "themeTint": val(child, "themeTint"),
                            "themeShade": val(child, "themeShade")}
        elif tag == "highlight":
            out["highlight"] = val(child)
        elif tag == "vertAlign":
            out["vertAlign"] = val(child)
        elif tag == "spacing":
            out["charSpacingPt"] = pt_from_twips(val(child))
        elif tag == "kern":
            out["kerningPt"] = pt_from_halfpoints(val(child))
        elif tag == "position":
            out["positionPt"] = pt_from_halfpoints(val(child))
        elif tag == "lang":
            out["lang"] = {"val": val(child), "eastAsia": val(child, "eastAsia"),
                           "bidi": val(child, "bidi")}
        elif tag == "rStyle":
            out["rStyle"] = val(child)
        elif tag == "shd":
            out["shading"] = {"fill": val(child, "fill"), "pattern": val(child, "val")}
        elif tag == "w":
            out["kernScale"] = int(val(child) or 100)
        elif tag == "effect":
            out["effect"] = val(child)
    return out


# ------------------------------------------------------------------- pPr ---
def parse_tabs(el: ET.Element) -> list[dict]:
    tabs = []
    for tab in el.findall(f"{W}tab"):
        tabs.append({"posMm": mm_from_twips(val(tab, "pos")), "align": val(tab),
                     "leader": val(tab, "leader")})
    return tabs


def parse_spacing(el: ET.Element) -> dict:
    out = {}
    if val(el, "before") is not None:
        out["beforePt"] = pt_from_twips(val(el, "before"))
    if val(el, "after") is not None:
        out["afterPt"] = pt_from_twips(val(el, "after"))
    if val(el, "beforeLines") is not None:
        out["beforeLines"] = int(val(el, "beforeLines")) / 100.0
    if val(el, "afterLines") is not None:
        out["afterLines"] = int(val(el, "afterLines")) / 100.0
    if val(el, "line") is not None:
        rule = val(el, "lineRule", "auto")
        raw = int(val(el, "line"))
        out["lineRule"] = rule
        if rule == "auto":
            out["line"] = round(raw / 240.0, 3)   # 240 = одинарный
        else:
            out["linePt"] = round(raw / 20.0, 2)  # atLeast / exact
    return out


def parse_ind(el: ET.Element) -> dict:
    mapping = {
        "left": "leftMm", "start": "leftMm", "right": "rightMm", "end": "rightMm",
        "firstLine": "firstLineMm", "hanging": "hangingMm",
    }
    out = {}
    for attr, key in mapping.items():
        if val(el, attr) is not None:
            out[key] = mm_from_twips(val(el, attr))
    if val(el, "leftChars") is not None:
        out["leftChars"] = int(val(el, "leftChars")) / 100.0
    if val(el, "hangingChars") is not None:
        out["hangingChars"] = int(val(el, "hangingChars")) / 100.0
    if val(el, "firstLineChars") is not None:
        out["firstLineChars"] = int(val(el, "firstLineChars")) / 100.0
    return out


def parse_numpr(el: ET.Element) -> dict:
    return {"numId": val(el.find(f"{W}numId")), "ilvl": val(el.find(f"{W}ilvl"))}


def parse_ppr(el: ET.Element | None, unknown: Counter | None = None) -> dict:
    if el is None:
        return {}
    out: dict = {}
    for child in el:
        tag = local(child.tag)
        if unknown is not None and tag not in PPR_KNOWN:
            unknown[f"pPr/{tag}"] += 1
        if tag == "pStyle":
            out["pStyle"] = val(child)
        elif tag == "jc":
            out["alignment"] = val(child)
        elif tag == "ind":
            out["indent"] = parse_ind(child)
        elif tag == "spacing":
            out["spacing"] = parse_spacing(child)
        elif tag in ("keepNext", "keepLines", "pageBreakBefore", "widowControl",
                     "contextualSpacing", "suppressLineNumbers", "wordWrap",
                     "autoSpaceDE", "autoSpaceDN", "snapToGrid", "bidi",
                     "adjustRightInd", "mirrorIndents"):
            out[tag] = on_off(child)
        elif tag == "outlineLvl":
            out["outlineLevel"] = int(val(child))
        elif tag == "numPr":
            out["numPr"] = parse_numpr(child)
        elif tag == "tabs":
            out["tabs"] = parse_tabs(child)
        elif tag == "rPr":
            out["runProperties"] = parse_rpr(child, unknown)
        elif tag == "pBdr":
            out["borders"] = {local(b.tag): {
                "style": val(b), "sizeEighthsPt": val(b, "sz"),
                "spacePt": val(b, "space"), "color": val(b, "color"),
            } for b in child}
        elif tag == "shd":
            out["shading"] = {"fill": val(child, "fill"), "pattern": val(child, "val")}
        elif tag == "textAlignment":
            out["textAlignment"] = val(child)
        elif tag == "textDirection":
            out["textDirection"] = val(child)
        elif tag == "sectPr":
            out["sectionBreak"] = True
    return out


# --------------------------------------------------------------- sectPr ---
def parse_sectpr(el: ET.Element | None) -> dict:
    if el is None:
        return {}
    out: dict = {}
    pgsz = el.find(f"{W}pgSz")
    if pgsz is not None:
        out["page"] = {
            "widthMm": mm_from_twips(val(pgsz, "w")),
            "heightMm": mm_from_twips(val(pgsz, "h")),
            "orientation": val(pgsz, "orient", "portrait"),
        }
    pgmar = el.find(f"{W}pgMar")
    if pgmar is not None:
        out["margins"] = {
            "topMm": mm_from_twips(val(pgmar, "top")),
            "rightMm": mm_from_twips(val(pgmar, "right")),
            "bottomMm": mm_from_twips(val(pgmar, "bottom")),
            "leftMm": mm_from_twips(val(pgmar, "left")),
            "headerMm": mm_from_twips(val(pgmar, "header")),
            "footerMm": mm_from_twips(val(pgmar, "footer")),
            "gutterMm": mm_from_twips(val(pgmar, "gutter")),
        }
    cols = el.find(f"{W}cols")
    if cols is not None:
        out["columns"] = {"count": val(cols, "num") or "1",
                          "spaceMm": mm_from_twips(val(cols, "space"))}
    grid = el.find(f"{W}docGrid")
    if grid is not None:
        out["docGrid"] = {"type": val(grid, "type"), "linePitchTwips": val(grid, "linePitch")}
    if el.find(f"{W}titlePg") is not None:
        out["titlePage"] = on_off(el.find(f"{W}titlePg"))
    pn = el.find(f"{W}pgNumType")
    if pn is not None:
        out["pageNumbering"] = {"fmt": val(pn, "fmt"), "start": val(pn, "start")}
    return out


# ----------------------------------------------------------------- theme ---
def parse_theme(xml: bytes | None) -> dict:
    if not xml:
        return {}
    root = ET.fromstring(xml)
    out: dict = {}
    scheme = root.find(f"{A}themeElements/{A}fontScheme")
    if scheme is not None:
        fonts = {}
        for role, tag in (("major", "majorFont"), ("minor", "minorFont")):
            node = scheme.find(f"{A}{tag}")
            if node is None:
                continue
            entry = {}
            for slot in ("latin", "ea", "cs"):
                sub = node.find(f"{A}{slot}")
                if sub is not None and sub.get("typeface"):
                    entry[slot] = sub.get("typeface")
            script_fonts = {f.get("script"): f.get("typeface") for f in node.findall(f"{A}font")}
            if script_fonts:
                entry["scriptOverrides"] = script_fonts
            fonts[role] = entry
        out["fonts"] = fonts
        out["fontSchemeName"] = scheme.get("name")
    cs = root.find(f"{A}themeElements/{A}clrScheme")
    if cs is not None:
        colors = {}
        for node in cs:
            name = local(node.tag)
            for child in node:
                colors[name] = child.get("lastClr") or child.get("val")
        out["colors"] = colors
        out["colorSchemeName"] = cs.get("name")
    return out


def resolve_theme_fonts(rfonts: dict, theme: dict) -> tuple[dict, dict, list]:
    """Разыменовать w:asciiTheme/w:hAnsiTheme/... через theme1.xml.

    Возвращает (resolved, source, conflicts):
      resolved  - слот -> фактический typeface;
      source    - слот -> "explicit" | "theme";
      conflicts - слоты, где в цепочке наследования одновременно пришли явное имя
                  и ссылка на тему. Это НЕ однозначный случай: ECMA-376 (CT_Fonts)
                  отдаёт приоритет theme-атрибуту, а Word/LibreOffice на практике
                  оставляют явное имя, унаследованное от базового стиля
                  (проверено рендером ГОСТ-шаблона в PDF - см. отчёт).
    """
    if not rfonts:
        return {}, {}, []
    slots = (("ascii", "asciiTheme"), ("hAnsi", "hAnsiTheme"),
             ("eastAsia", "eastAsiaTheme"), ("cs", "cstheme"))
    resolved: dict = {}
    source: dict = {}
    conflicts: list = []
    for slot, key in slots:
        explicit = rfonts.get(slot)
        theme_ref = rfonts.get(key)
        theme_face = None
        if theme_ref and theme.get("fonts"):
            match = re.match(r"(major|minor)(Ascii|HAnsi|EastAsia|Bidi)", theme_ref)
            role = match.group(1) if match else (
                "major" if theme_ref.startswith("major") else "minor")
            kind = match.group(2) if match else "HAnsi"
            a_slot = {"Ascii": "latin", "HAnsi": "latin", "EastAsia": "ea", "Bidi": "cs"}[kind]
            theme_face = theme["fonts"].get(role, {}).get(a_slot)
        if explicit and theme_face and explicit != theme_face:
            conflicts.append({"slot": slot, "explicit": explicit,
                              "themeRef": theme_ref, "themeValue": theme_face,
                              "policy": "explicit-wins"})
            resolved[slot] = explicit
            source[slot] = "explicit"
        elif explicit:
            resolved[slot] = explicit
            source[slot] = "explicit"
        elif theme_face:
            resolved[slot] = theme_face
            source[slot] = "theme"
    return resolved, source, conflicts


# ---------------------------------------------------------------- styles ---
def parse_style(node: ET.Element, unknown: Counter) -> dict:
    out = {
        "id": node.get(f"{W}styleId"),
        "type": node.get(f"{W}type", "paragraph"),
        "default": node.get(f"{W}default") in ("1", "true", "on"),
        "name": val(node.find(f"{W}name")),
        "basedOn": val(node.find(f"{W}basedOn")),
        "next": val(node.find(f"{W}next")),
        "link": val(node.find(f"{W}link")),
        "uiPriority": val(node.find(f"{W}uiPriority")),
        "qFormat": on_off(node.find(f"{W}qFormat")),
        "semiHidden": on_off(node.find(f"{W}semiHidden")),
        "unhideWhenUsed": on_off(node.find(f"{W}unhideWhenUsed")),
        "autoRedefine": on_off(node.find(f"{W}autoRedefine")),
        "aliases": val(node.find(f"{W}aliases")),
    }
    ppr = node.find(f"{W}pPr")
    rpr = node.find(f"{W}rPr")
    if ppr is not None:
        out["paragraphProperties"] = parse_ppr(ppr, unknown)
    if rpr is not None:
        out["runProperties"] = parse_rpr(rpr, unknown)
    tbl = node.find(f"{W}tblPr")
    if tbl is not None:
        out["tableProperties"] = {local(c.tag): {
            k.rsplit("}", 1)[-1]: v for k, v in c.attrib.items()} for c in tbl}
    conditional = []
    for c in node.findall(f"{W}tblStylePr"):
        entry = {
            "type": c.get(f"{W}type"),
            "runProperties": parse_rpr(c.find(f"{W}rPr"), unknown),
            "paragraphProperties": parse_ppr(c.find(f"{W}pPr"), unknown),
        }
        tblpr = c.find(f"{W}tblPr")
        if tblpr is not None:
            entry["tableProperties"] = {local(x.tag): dict(x.attrib) for x in tblpr}
        conditional.append(entry)
    if conditional:
        out["conditionalFormats"] = conditional
    return out


def deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def effective_styles(styles: list[dict], doc_defaults: dict) -> dict:
    by_id = {s["id"]: s for s in styles}
    flat: dict = {}
    seen: set[str] = set()

    def resolve(style_id: str) -> dict:
        if style_id in flat:
            return flat[style_id]
        if style_id in seen:               # защита от циклов basedOn
            return {"runProperties": {}, "paragraphProperties": {}}
        seen.add(style_id)
        style = by_id.get(style_id)
        if style is None:
            return {"runProperties": {}, "paragraphProperties": {}}
        parent = resolve(style["basedOn"]) if style.get("basedOn") else {
            "runProperties": doc_defaults.get("runProperties", {}),
            "paragraphProperties": doc_defaults.get("paragraphProperties", {}),
        }
        merged = {
            "runProperties": deep_merge(parent.get("runProperties", {}),
                                        style.get("runProperties", {})),
            "paragraphProperties": deep_merge(parent.get("paragraphProperties", {}),
                                              style.get("paragraphProperties", {})),
        }
        flat[style_id] = merged
        return merged

    return {sid: resolve(sid) for sid in by_id}


# -------------------------------------------------------------- numbering ---
def parse_numbering(xml: bytes | None, unknown: Counter) -> dict:
    if not xml:
        return {}
    root = ET.fromstring(xml)
    abstracts = []
    for node in root.findall(f"{W}abstractNum"):
        levels = []
        for lvl in node.findall(f"{W}lvl"):
            fmt = val(lvl.find(f"{W}numFmt"))
            levels.append({
                "ilvl": int(lvl.get(f"{W}ilvl", 0)),
                "start": val(lvl.find(f"{W}start")),
                "numFmt": fmt,
                "example": NUMFMT_HUMAN.get(fmt),
                "lvlText": val(lvl.find(f"{W}lvlText")),
                "suff": val(lvl.find(f"{W}suff")),
                "lvlJc": val(lvl.find(f"{W}lvlJc")),
                "paragraphProperties": parse_ppr(lvl.find(f"{W}pPr"), unknown),
                "runProperties": parse_rpr(lvl.find(f"{W}rPr"), unknown),
                "pStyle": val(lvl.find(f"{W}pStyle")),
            })
        abstracts.append({
            "abstractNumId": node.get(f"{W}abstractNumId"),
            "multiLevelType": val(node.find(f"{W}multiLevelType")),
            "numStyleLink": val(node.find(f"{W}numStyleLink")),
            "levels": levels,
        })
    nums = [{"numId": n.get(f"{W}numId"),
             "abstractNumId": val(n.find(f"{W}abstractNumId")),
             "overrides": [{"ilvl": o.get(f"{W}ilvl"),
                            "startOverride": val(o.find(f"{W}startOverride"))}
                           for o in n.findall(f"{W}lvlOverride")]}
            for n in root.findall(f"{W}num")]
    return {"abstractNums": abstracts, "nums": nums}


# ---------------------------------------------------------- роли стилей ---
# Канонические роли, нужные рендереру. Порядок детекции:
#   1) стандартный styleId Word (Heading1, Title, ...) - самый надёжный;
#   2) outlineLevel в pPr (стили-заголовки, даже с локализованными именами);
#   3) шаблон имени (EN + RU), включая "Раздел"/"Подраздел"/"Название рисунка".
BUILTIN_ROLES = {
    "Title": "title", "Subtitle": "subtitle", "Normal": "body",
    "Caption": "caption", "Quote": "quote", "BlockText": "quote",
    "SourceCode": "code", "VerbatimChar": "codeInline", "MacroText": "code",
    "FootnoteText": "footnote", "Header": "pageHeader", "Footer": "pageFooter",
    "ListParagraph": "listItem", "ListBullet": "listBullet", "ListNumber": "listNumber",
    "TableGrid": "tableBody", "TableofFigures": "tocFigure", "TOCHeading": "tocHeading",
    "Strong": "strong", "Emphasis": "emphasis", "Hyperlink": "link",
}
for _i in range(1, 10):
    BUILTIN_ROLES[f"Heading{_i}"] = f"heading{_i}"
    BUILTIN_ROLES[f"TOC{_i}"] = f"toc{_i}"

NAME_ROLE_PATTERNS = [
    (r"^(heading|заголовок)\s*([1-9])$", "heading{n}"),
    (r"^(heading|заголовок)$", "heading?"),
    (r"назван\w*\s+рисун|figure\s*caption|^caption\s*(figure|image)|image caption", "figureCaption"),
    (r"назван\w*\s+таблиц|table\s*caption", "tableCaption"),
    (r"заголовок\s+графы|table\s*header|шапка\s+таблицы", "tableHeader"),
    (r"текст\s+таблицы|табличн\w*\s+текст|table\s*(body|text)", "tableText"),
    (r"боковик", "tableStub"),
    (r"^toc\s*([1-9])$", "toc{n}"),
    (r"^(toc|оглавление|содержание)$", "tocEntry"),
    (r"изображени\w*\s+рисунка|^figure$|captioned figure", "figure"),
    (r"подпись\s+уравнени|equation\s*caption", "equationCaption"),
    (r"^(bullet|list bullet|список\s+маркирован)", "listBullet"),
    (r"^(list\s*number|нумерованн\w*\s+список)", "listNumber"),
    (r"^list paragraph|^список", "listItem"),
    (r"^title$|^название\s+документа", "title"),
    (r"^subtitle$|^подзаголовок", "subtitle"),
    (r"^body text$|^основной\s+текст$|^normal$|^обычный$", "body"),
    (r"^quote$|^цитата$|block text", "quote"),
    (r"^source code$|^code$|^код$|^листинг$", "code"),
    (r"^footnote|^сноск", "footnote"),
    (r"^header$|^колонтитул\s+верхн", "pageHeader"),
    (r"^footer$|^колонтитул\s+нижн", "pageFooter"),
    (r"уравнени|equation", "equation"),
    (r"приложени|appendix", "appendixHeading"),
    (r"^annotation|^balloon", "annotation"),
]


VIA_PRIORITY = {"builtinStyleId": 0, "outlineLevel": 1, "styleName": 2}


def map_roles(styles: list[dict], effective: dict, usage: dict | None = None) -> dict:
    """Сопоставить стили документа каноническим ролям.

    usage - {styleId: сколько_абзацев_использует}. Использование решает спор
    кандидатов: в реальных файлах роль "heading 1" часто занята неиспользуемым
    встроенным стилем, а фактический заголовок - локализованный "Раздел".
    """
    usage = usage or {}
    by_id = {s["id"]: s for s in styles}
    candidates: dict[str, list[dict]] = {}

    def add(role: str, style: dict, via: str, extra: dict | None = None):
        entry = {"styleId": style["id"], "styleName": style["name"], "via": via,
                 "usedParagraphs": usage.get(style["id"], 0)}
        if extra:
            entry.update(extra)
        bucket = candidates.setdefault(role, [])
        if all(c["styleId"] != entry["styleId"] for c in bucket):
            bucket.append(entry)

    for style in styles:
        if style["type"] != "paragraph":
            continue
        builtin = BUILTIN_ROLES.get(style["id"])
        if builtin:
            add(builtin, style, "builtinStyleId")
        name = (style.get("name") or "").strip()
        for pattern, target in NAME_ROLE_PATTERNS:
            match = re.match(pattern, name, re.I)
            if not match:
                continue
            digits = [g for g in match.groups() if g and g.isdigit()]
            role = target.replace("{n}", digits[0]) if "{n}" in target and digits else target
            add(role, style, "styleName")
            break

    # Заголовки по outlineLevel: работает и для локализованных имён ("Раздел").
    outlines = {}
    for style in styles:
        if style["type"] != "paragraph":
            continue
        level = (effective.get(style["id"], {}).get("paragraphProperties") or {}).get("outlineLevel")
        if level is not None and int(level) < 9:
            outlines[style["id"]] = int(level)
    outline_base = None
    if outlines:
        outline_base = min(outlines.values())
        for style_id, level in outlines.items():
            add(f"heading{level - outline_base + 1}", by_id[style_id], "outlineLevel",
                {"rawOutlineLevel": level})

    roles: dict = {}
    warnings: list[str] = []
    for role, bucket in candidates.items():
        bucket.sort(key=lambda c: (-c["usedParagraphs"], VIA_PRIORITY[c["via"]]))
        primary = bucket[0]
        alternates = bucket[1:]
        entry = dict(primary)
        if alternates:
            entry["alternates"] = alternates
        roles[role] = entry
        if primary["usedParagraphs"] == 0 and any(a["usedParagraphs"] for a in alternates):
            warnings.append(f"роль {role}: выбран неиспользуемый стиль "
                            f"{primary['styleName']!r}, используемый кандидат - "
                            f"{alternates[0]['styleName']!r}")
    if outline_base not in (None, 0):
        warnings.append(f"верхний уровень заголовков в файле - outlineLevel={outline_base} "
                        f"(не 0); уровни нормализованы к heading1..N")
    return {"roles": roles, "warnings": warnings, "outlineLevelBase": outline_base}


# --------------------------------------------------------------- документ ---
def document_stats(xml: bytes | None) -> dict:
    if not xml:
        return {}
    root = ET.fromstring(xml)
    body = root.find(f"{W}body")
    if body is None:
        return {}
    paragraphs = body.findall(f".//{W}p")
    runs = body.findall(f".//{W}r")
    p_with_ppr = p_with_pstyle = p_direct_fmt = 0
    r_with_rpr = 0
    used_styles: Counter = Counter()
    used_rstyles: Counter = Counter()
    for p in paragraphs:
        ppr = p.find(f"{W}pPr")
        if ppr is None:
            continue
        p_with_ppr += 1
        pstyle = val(ppr.find(f"{W}pStyle"))
        if pstyle:
            p_with_pstyle += 1
            used_styles[pstyle] += 1
        direct = [c for c in ppr if local(c.tag) not in ("pStyle", "rPr", "sectPr")]
        if direct:
            p_direct_fmt += 1
    for r in runs:
        rpr = r.find(f"{W}rPr")
        if rpr is not None:
            r_with_rpr += 1
            rs = val(rpr.find(f"{W}rStyle"))
            if rs:
                used_rstyles[rs] += 1
    return {
        "paragraphs": len(paragraphs),
        "runs": len(runs),
        "tables": len(body.findall(f".//{W}tbl")),
        "sections": len(body.findall(f".//{W}sectPr")) + (1 if body.find(f"{W}sectPr") is not None else 0),
        "tocFields": len(body.findall(f".//{W}fldSimple")) + len(body.findall(f".//{W}instrText")),
        "images": len(body.findall(f".//{W}drawing")),
        "paragraphsWithStyle": p_with_pstyle,
        "paragraphsWithDirectFormatting": p_direct_fmt,
        "runsWithDirectFormatting": r_with_rpr,
        "directFormattingShare": round(
            (p_direct_fmt + r_with_rpr) / max(len(paragraphs) + len(runs), 1), 3),
        "paragraphStyleUsage": dict(used_styles.most_common()),
        "characterStyleUsage": dict(used_rstyles.most_common()),
        "leadingFormattingOrder": list(used_styles.most_common(12)),
    }


def dominant_formatting(parts: dict, styles: list[dict], effective: dict,
                        defaults: dict, theme: dict, top: int = 5) -> dict:
    """Мода фактического оформления - "оформление по факту", а не по стилям.

    Нужна для документов без стилевой дисциплины: абзацы могут вообще не
    использовать pStyle, а полагаться на прямое форматирование. Здесь мы
    собираем эффективные свойства каждого абзаца/прогона (docDefaults ->
    pStyle -> pPr/rPr -> прямое rPr) и считаем самые частые комбинации.
    """
    xml = parts.get("word/document.xml")
    if not xml:
        return {}
    body = ET.fromstring(xml).find(f"{W}body")
    if body is None:
        return {}
    run_keys: Counter = Counter()
    para_keys: Counter = Counter()
    paragraphs = body.findall(f".//{W}p")
    for p in paragraphs:
        ppr = p.find(f"{W}pPr")
        pstyle = val(ppr.find(f"{W}pStyle")) if ppr is not None else None
        base = effective.get(pstyle or "", {})
        base_rp = base.get("runProperties") or defaults.get("runProperties") or {}
        base_pp = base.get("paragraphProperties") or defaults.get("paragraphProperties") or {}

        own_pp = parse_ppr(ppr) if ppr is not None else {}
        own_pp.pop("runProperties", None)
        merged_pp = deep_merge(base_pp, own_pp)
        indent = merged_pp.get("indent") or {}
        spacing = merged_pp.get("spacing") or {}
        para_keys[(
            merged_pp.get("alignment"),
            indent.get("firstLineMm"),
            indent.get("leftMm"),
            spacing.get("line") if spacing.get("lineRule") == "auto" else spacing.get("linePt"),
            spacing.get("lineRule"),
            spacing.get("beforePt"),
            spacing.get("afterPt"),
            bool(merged_pp.get("keepNext")),
        )] += 1

        for r in p.findall(f".//{W}r"):
            merged_rp = deep_merge(base_rp, parse_rpr(r.find(f"{W}rPr")))
            font = merged_rp.get("fontResolved") or {}
            colour = (merged_rp.get("color") or {}).get("hex")
            run_keys[(
                font.get("ascii"), merged_rp.get("sizePt"), bool(merged_rp.get("bold")),
                bool(merged_rp.get("italic")), bool(merged_rp.get("underline")), colour,
            )] += 1

    def unpack_para(key, count):
        jc, first_line, left, line, line_rule, before, after, keep_next = key
        return {
            "alignment": jc, "firstLineMm": first_line, "leftMm": left,
            "line": line, "lineRule": line_rule,
            "beforePt": before, "afterPt": after, "keepNext": keep_next,
            "paragraphs": count,
        }

    def unpack_run(key, count):
        font, size, bold, italic, underline, colour = key
        return {"font": font, "sizePt": size, "bold": bold, "italic": italic,
                "underline": underline, "color": colour, "runs": count}

    total_p = sum(para_keys.values()) or 1
    total_r = sum(run_keys.values()) or 1
    return {
        "paragraphsTotal": total_p,
        "runsTotal": total_r,
        "topParagraphFormats": [
            {**unpack_para(k, c), "share": round(c / total_p, 3)}
            for k, c in para_keys.most_common(top)
        ],
        "topRunFormats": [
            {**unpack_run(k, c), "share": round(c / total_r, 3)}
            for k, c in run_keys.most_common(top)
        ],
    }


def app_info(parts: dict) -> dict:
    info = {}
    core = parts.get("docProps/core.xml")
    if core:
        root = ET.fromstring(core)
        for el in root:
            tag = local(el.tag)
            if el.text and tag in ("creator", "lastModifiedBy", "created", "modified",
                                   "title", "revision"):
                info[tag] = el.text.strip()
    app = parts.get("docProps/app.xml")
    if app:
        root = ET.fromstring(app)
        for el in root:
            tag = local(el.tag)
            if el.text and tag in ("Application", "AppVersion", "Template", "Pages", "Words"):
                info[tag] = el.text.strip()
    return info


def settings_info(xml: bytes | None) -> dict:
    if not xml:
        return {}
    root = ET.fromstring(xml)
    keys = ("defaultTabStop", "characterSpacingControl", "compat", "themeFontLang",
            "evenAndOddHeaders", "trackChanges", "documentProtection", "proofState",
            "hyphenationZone", "autoHyphenation")
    out = {}
    for child in root:
        tag = local(child.tag)
        if tag in keys:
            out[tag] = dict(child.attrib) if child.attrib else True
    return out


# -------------------------------------------------------------- контейнер ---
class UnsupportedDocument(Exception):
    """Файл не является OOXML-документом, который мы умеем разбирать."""


def read_parts(path: Path) -> dict:
    wanted = {
        "word/styles.xml", "word/stylesWithEffects.xml", "word/theme/theme1.xml",
        "word/numbering.xml", "word/document.xml", "word/settings.xml",
        "word/fontTable.xml", "docProps/core.xml", "docProps/app.xml",
        "word/footnotes.xml", "word/endnotes.xml",
    }
    parts = {}
    with path.open("rb") as fh:
        magic = fh.read(8)
    if magic.startswith(b"\xd0\xcf\x11\xe0"):
        # OLE/CFB: старый .doc, .docm с защитой паролем или IRM-контейнер
        raise UnsupportedDocument(
            "OLE/CFB-контейнер (.doc, зашифрованный или IRM-защищённый файл) - "
            "не OOXML; требуется предварительная конвертация (LibreOffice --convert-to docx)")
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise UnsupportedDocument(f"не zip-контейнер OPC: {exc}") from exc
    with zf:
        names = set(zf.namelist())
        if "word/styles.xml" not in names:
            raise UnsupportedDocument(
                "нет word/styles.xml: это не WordprocessingML (возможно, ODT/ODP/PDF)")
        for name in wanted & names:
            parts[name] = zf.read(name)
        parts["__names__"] = sorted(names)
    return parts


def extract(path: Path, with_effective: bool = True) -> dict:
    try:
        parts = read_parts(path)
    except UnsupportedDocument as exc:
        raise SystemExit(f"{path.name}: {exc}") from exc
    unknown: Counter = Counter()

    styles_root = ET.fromstring(parts["word/styles.xml"])
    defaults: dict = {}
    dt = styles_root.find(f"{W}docDefaults")
    if dt is not None:
        defaults = {
            "runProperties": parse_rpr(dt.find(f"{W}rPrDefault/{W}rPr"), unknown),
            "paragraphProperties": parse_ppr(dt.find(f"{W}pPrDefault/{W}pPr"), unknown),
        }
    latent = styles_root.find(f"{W}latentStyles")
    latent_info = None
    if latent is not None:
        latent_info = {
            "count": latent.get(f"{W}count"),
            "exceptions": len(latent.findall(f"{W}lsdException")),
            "qFormatExceptions": sum(1 for e in latent.findall(f"{W}lsdException")
                                     if e.get(f"{W}qFormat") in ("1", "true", "on")),
        }

    known_style_children = {
        "name", "aliases", "basedOn", "next", "link", "autoRedefine", "hidden",
        "uiPriority", "semiHidden", "unhideWhenUsed", "qFormat", "locked",
        "personal", "personalCompose", "personalReply", "rsid", "pPr", "rPr",
        "tblPr", "trPr", "tcPr", "tblStylePr",
    }
    for node in styles_root.findall(f"{W}style"):
        for child in node:
            tag = local(child.tag)
            if tag not in known_style_children:
                unknown[f"style/{tag}"] += 1
    for child in styles_root:
        tag = local(child.tag)
        if tag not in ("docDefaults", "latentStyles", "style"):
            unknown[f"styles/{tag}"] += 1

    styles = [parse_style(node, unknown) for node in styles_root.findall(f"{W}style")]
    theme = parse_theme(parts.get("word/theme/theme1.xml"))

    # Разыменование theme-шрифтов: в ГОСТ-шаблонах шрифт часто задан не именем,
    # а ссылкой на тему (w:asciiTheme="minorHAnsi"), без разыменования получим пустоту.
    def deref(container: dict):
        rpr = container.get("runProperties") or {}
        font = rpr.get("font")
        if font:
            resolved, source, conflicts = resolve_theme_fonts(font, theme)
            if resolved:
                rpr["fontResolved"] = resolved
                rpr["fontResolvedSource"] = source
            if conflicts:
                rpr["fontConflicts"] = conflicts

    deref(defaults)
    for s in styles:
        deref(s)
        deref({"runProperties": (s.get("paragraphProperties") or {}).get("runProperties") or {}})

    doc = ET.fromstring(parts["word/document.xml"])
    body = doc.find(f"{W}body")
    section = parse_sectpr(body.find(f"{W}sectPr") if body is not None else None)

    result = {
        "schemaVersion": "0.1-poc",
        "source": {
            "file": path.name,
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "parts": [n for n in parts["__names__"] if n.endswith(".xml")][:40],
            "app": app_info(parts),
        },
        "page": section,
        "theme": theme,
        "docDefaults": defaults,
        "latentStyles": latent_info,
        "styles": styles,
        "numbering": parse_numbering(parts.get("word/numbering.xml"), unknown),
        "settings": settings_info(parts.get("word/settings.xml")),
        "document": document_stats(parts.get("word/document.xml")),
        "coverage": {
            "styleCount": len(styles),
            "byType": dict(Counter(s["type"] for s in styles)),
            "unsupportedElements": dict(unknown.most_common()),
        },
    }
    if with_effective:
        effective = effective_styles(styles, defaults)
        for eff in effective.values():
            deref(eff)
        result["effectiveStyles"] = effective
    result["styleIndex"] = {s["name"]: s["id"] for s in styles if s.get("name")}
    usage = (result["document"].get("paragraphStyleUsage")
             if with_effective else {}) or {}
    result["roleMapping"] = map_roles(styles, result.get("effectiveStyles", {}), usage)
    result["dominantFormatting"] = dominant_formatting(
        parts, styles, result.get("effectiveStyles", {}), defaults, theme)
    # styleId в реальных файлах бывает непрозрачным ("aff9", "31"), поэтому
    # статистику использования переводим в имена стилей.
    id_to_name = {s["id"]: s["name"] for s in styles if s.get("name")}
    usage = result["document"].get("paragraphStyleUsage") or {}
    result["document"]["paragraphStyleUsageByName"] = {
        id_to_name.get(sid, sid): count for sid, count in usage.items()
    }
    return result


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("docx", type=Path)
    ap.add_argument("-o", "--out", type=Path, help="куда писать JSON (по умолчанию stdout)")
    ap.add_argument("--no-effective", action="store_true",
                    help="не вычислять эффективные (унаследованные) стили")
    args = ap.parse_args(argv)
    data = extract(args.docx, with_effective=not args.no_effective)
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"{args.docx}: {len(data['styles'])} стилей -> {args.out}")
        return 0
    try:
        print(text)
    except BrokenPipeError:
        # `| head` закрывает пайп раньше - это не ошибка
        try:
            sys.stdout.close()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    sys.exit(main(sys.argv[1:]))
