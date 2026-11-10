#!/usr/bin/env python3
"""Читатель подмножества YAML для скриптов автоматизации.

Полноценный YAML-парсер в стандартную библиотеку Python не входит, а тянуть зависимость ради
документации и генерации DDL не хочется. Поддержано ровно то, что встречается в наших файлах:
отображения, списки, скаляры и блочные строки (`|`, `>`). Всё остальное — `YamlSubsetError`
с номером строки: тихо неверный результат хуже громкой ошибки.

Использование:
    from yaml_subset import YamlSubset, YamlSubsetError
    data = YamlSubset(text, "path/to/file.yml").parse()
"""
from __future__ import annotations

import re


def collapse(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


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
