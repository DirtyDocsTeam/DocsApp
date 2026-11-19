"""Small, strict DDL model for Spectra's ordered PostgreSQL migrations.

This models CREATE/ALTER TABLE, keys and indexes; it does not execute SQL or
interpret function bodies. The generated db.sql retains the original DDL.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

IDENT = r'(?:"[^"]+"|[A-Za-z_]\w*)(?:\.(?:"[^"]+"|[A-Za-z_]\w*))*'


@dataclass
class Column:
    name: str
    type: str
    nullable: bool = True
    primary: bool = False
    reference: tuple[str, str] | None = None
    indexed: bool = False
    unique: bool = False
    trigger: bool = False
    references: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class ForeignKey:
    columns: tuple[str, ...]
    parent: str
    parent_columns: tuple[str, ...]
    name: str = ''


@dataclass
class Table:
    name: str
    columns: list[Column] = field(default_factory=list)
    annotations: list[str] = field(default_factory=list)
    foreign_keys: list[ForeignKey] = field(default_factory=list)
    keys: dict[str, tuple[str, tuple[str, ...]]] = field(default_factory=dict)

    def column(self, name: str) -> Column | None:
        return next((column for column in self.columns if column.name == name), None)


def name(raw: str) -> str:
    return raw.split('.')[-1].strip('"')


def parts(text: str, delimiter: str = ',') -> list[str]:
    """Split outside parentheses, SQL quotes and dollar-quoted function bodies."""
    result, current = [], []
    depth, i = 0, 0
    while i < len(text):
        if text.startswith('--', i):
            end = text.find('\n', i)
            i = len(text) if end < 0 else end
            current.append(' ')
            continue
        if text.startswith('/*', i):
            end = text.find('*/', i + 2)
            if end < 0:
                raise ValueError('Unclosed SQL comment')
            i = end + 2
            current.append(' ')
            continue
        char = text[i]
        if char in "'\"":
            start, quote = i, char
            i += 1
            while i < len(text):
                if text[i] == quote:
                    i += 1
                    if i < len(text) and text[i] == quote:
                        i += 1
                        continue
                    break
                i += 1
            else:
                raise ValueError('Unclosed SQL quote')
            current.append(text[start:i])
            continue
        dollar = re.match(r'\$(?:[A-Za-z_]\w*)?\$', text[i:]) if char == '$' else None
        if dollar:
            tag = dollar.group()
            end = text.find(tag, i + len(tag))
            if end < 0:
                raise ValueError('Unclosed dollar-quoted SQL body')
            current.append(text[i:end + len(tag)])
            i = end + len(tag)
            continue
        if char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
        if char == delimiter and depth == 0:
            result.append(''.join(current).strip())
            current = []
        else:
            current.append(char)
        i += 1
    if depth != 0:
        raise ValueError('Unbalanced SQL parentheses')
    if ''.join(current).strip():
        result.append(''.join(current).strip())
    return result


def columns(raw: str) -> tuple[str, ...]:
    return tuple(name(item.strip()) for item in parts(raw))


def constraint(table: Table, sql: str) -> bool:
    match = re.match(rf'CONSTRAINT\s+({IDENT})\s+(.*)', sql, re.I | re.S)
    key_name = name(match[1]) if match else ''
    body = match[2] if match else sql
    fk = re.match(rf'FOREIGN\s+KEY\s*\((.*?)\)\s+REFERENCES\s+({IDENT})\s*\((.*?)\)', body, re.I | re.S)
    if fk:
        table.foreign_keys.append(ForeignKey(columns(fk[1]), name(fk[2]), columns(fk[3]), key_name))
        return True
    key = re.match(r'(PRIMARY\s+KEY|UNIQUE)\s*\((.*?)\)', body, re.I | re.S)
    if key:
        kind = 'PK' if key[1].upper().startswith('PRIMARY') else 'UQ'
        table.keys[key_name or f'{kind}:{key[2]}'] = kind, columns(key[2])
        return True
    return bool(re.match(r'CHECK\s*\(', body, re.I))


def add_column(table: Table, sql: str) -> None:
    match = re.match(rf'({IDENT})\s+(.+)', sql.strip(), re.S)
    if not match:
        raise ValueError(f'Invalid column in {table.name}: {sql[:80]}')
    rest = match[2].strip()
    cut = re.search(r'\b(?:NOT\s+NULL|NULL|DEFAULT|PRIMARY\s+KEY|UNIQUE|REFERENCES|CHECK|GENERATED|CONSTRAINT|COLLATE)\b', rest, re.I)
    type_text = re.sub(r'\s+', ' ', rest[:cut.start()] if cut else rest).strip()
    col = Column(name(match[1]), type_text, nullable=not bool(re.search(r'\bNOT\s+NULL\b', rest, re.I)))
    if table.column(col.name):
        raise ValueError(f'Duplicate column {table.name}.{col.name}')
    table.columns.append(col)
    if re.search(r'\bPRIMARY\s+KEY\b', rest, re.I):
        table.keys[f'PK:{col.name}'] = 'PK', (col.name,)
    elif re.search(r'\bUNIQUE\b', rest, re.I):
        table.keys[f'UQ:{col.name}'] = 'UQ', (col.name,)
    fk = re.search(rf'REFERENCES\s+({IDENT})\s*\((.*?)\)', rest, re.I | re.S)
    if fk:
        table.foreign_keys.append(ForeignKey((col.name,), name(fk[1]), columns(fk[2])))


def parse_ddl(sql: str) -> list[Table]:
    tables: dict[str, Table] = {}
    indexes = []
    for statement in parts(sql, ';'):
        create = re.match(rf'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?({IDENT})\s*\((.*)\)\s*$', statement, re.I | re.S)
        if create:
            table = Table(name(create[1]))
            if table.name in tables:
                raise ValueError(f'Duplicate table {table.name}')
            tables[table.name] = table
            for definition in parts(create[2]):
                if not constraint(table, definition):
                    add_column(table, definition)
            continue
        alter = re.match(rf'ALTER\s+TABLE\s+({IDENT})\s+(.+)', statement, re.I | re.S)
        if alter:
            table = tables.get(name(alter[1]))
            if table is None:
                raise ValueError(f'ALTER references unknown table {alter[1]}')
            for action in parts(alter[2]):
                add = re.match(r'ADD\s+(?:COLUMN\s+)?(.+)', action, re.I | re.S)
                if add:
                    if not constraint(table, add[1]):
                        add_column(table, add[1])
                    continue
                drop = re.match(rf'DROP\s+CONSTRAINT\s+(?:IF\s+EXISTS\s+)?({IDENT})\s*$', action, re.I)
                if drop:
                    table.keys.pop(name(drop[1]), None)
                    table.foreign_keys = [fk for fk in table.foreign_keys if fk.name != name(drop[1])]
                    continue
                drop_column = re.match(rf'DROP\s+COLUMN\s+(?:IF\s+EXISTS\s+)?({IDENT})\s*$', action, re.I)
                if drop_column:
                    column_name = name(drop_column[1])
                    table.columns = [column for column in table.columns if column.name != column_name]
                    table.keys = {
                        key: (kind, names)
                        for key, (kind, names) in table.keys.items()
                        if column_name not in names
                    }
                    table.foreign_keys = [fk for fk in table.foreign_keys if fk.column != column_name]
                    continue
                change = re.match(rf'ALTER\s+(?:COLUMN\s+)?({IDENT})\s+(.+)', action, re.I | re.S)
                if change:
                    col = table.column(name(change[1]))
                    if col is None:
                        raise ValueError(f'Unknown column {table.name}.{change[1]}')
                    operation = change[2].strip()
                    if re.match(r'TYPE\s+', operation, re.I):
                        col.type = re.split(r'\s+USING\s+', re.sub(r'^TYPE\s+', '', operation, flags=re.I), flags=re.I)[0].strip()
                    elif re.fullmatch(r'SET\s+NOT\s+NULL', operation, re.I):
                        col.nullable = False
                    elif re.fullmatch(r'DROP\s+NOT\s+NULL', operation, re.I):
                        col.nullable = True
                    elif not re.match(r'(?:SET\s+DEFAULT|DROP\s+DEFAULT)\b', operation, re.I):
                        raise ValueError(f'Unsupported ALTER COLUMN: {action[:100]}')
                    continue
                raise ValueError(f'Unsupported ALTER TABLE: {action[:100]}')
            continue
        if re.match(r'CREATE\s+TABLE\b|ALTER\s+TABLE\b|DROP\s+TABLE\b', statement, re.I):
            raise ValueError(f'Unsupported table DDL: {statement[:100]}')
        index = re.match(rf'CREATE\s+(UNIQUE\s+)?INDEX\s+({IDENT})\s+ON\s+({IDENT})\s*(?:USING\s+\w+\s*)?\((.*?)\)(?:\s+WHERE\s+(.*))?$', statement, re.I | re.S)
        if index:
            indexes.append((name(index[3]), bool(index[1]), index[4], index[5]))

    for table in tables.values():
        for kind, names in table.keys.values():
            for key_name in names:
                col = table.column(key_name)
                if col is None:
                    raise ValueError(f'Unknown key column {table.name}.{key_name}')
                if kind == 'PK':
                    col.primary, col.nullable = True, False
                if len(names) == 1:
                    col.unique = True
            if len(names) > 1:
                table.annotations.append(kind + ' ' + ', '.join(names))
        for fk in table.foreign_keys:
            if len(fk.columns) != len(fk.parent_columns):
                raise ValueError(f'Invalid foreign key in {table.name}')
            for child, parent_col in zip(fk.columns, fk.parent_columns):
                col = table.column(child)
                if col is None or fk.parent not in tables or tables[fk.parent].column(parent_col) is None:
                    raise ValueError(f'Invalid FK {table.name}.{child} -> {fk.parent}.{parent_col}')
                ref = (fk.parent, parent_col)
                if ref not in col.references:
                    col.references.append(ref)
                col.reference = col.reference or ref
            if len(fk.columns) > 1:
                table.annotations.append('FK (' + ', '.join(fk.columns) + ') → ' + fk.parent + '(' + ', '.join(fk.parent_columns) + ')')
    for table_name, unique, expr, predicate in indexes:
        table = tables[table_name]
        simple = re.fullmatch(r'\s*(\w+)\s*(?:ASC|DESC)?\s*', expr, re.I)
        col = table.column(simple[1]) if simple else None
        if col:
            col.indexed, col.unique = True, col.unique or (unique and not predicate)
        if not col or predicate:
            label = expr + (' WHERE ' + predicate if predicate else '')
            table.annotations.append(('UQ ' if unique else 'IDX ') + re.sub(r'\s+', ' ', label))
    for trigger in re.finditer(rf'CREATE\s+TRIGGER\s+(\w+)\s+.*?\bON\s+({IDENT})\s+.*?EXECUTE\s+FUNCTION\s+({IDENT})', sql, re.I | re.S):
        table = tables.get(name(trigger[2]))
        if table:
            table.annotations.append('TRG ' + trigger[1])
    return sorted(tables.values(), key=lambda table: table.name)


def column_references(col: Column) -> list[tuple[str, str]]:
    return list(dict.fromkeys(([col.reference] if col.reference else []) + col.references))
