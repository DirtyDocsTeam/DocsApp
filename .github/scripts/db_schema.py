#!/usr/bin/env python3
"""Единый DDL и ERD из Liquibase-чанжлога.

Источник правды по схеме — Liquibase-чанжлог в
`backend/api/src/main/resources/db/changelog/`. Скрипт разворачивает master-файл
(`include`/`includeAll`/инлайновые `changeSet`) в один DDL `documentation/design/db.sql`,
а по команде перерисовывает ERD в `documentation/design/schema.png`.

ERD рисует https://sqltoerdiagram.com: инструмент полностью клиентский (SQL никуда не
отправляется), поэтому картинка снимается headless-браузером с share-ссылки `#s=…`.
Нужен docker с образом `zenika/alpine-chrome` или локальный chromium; без них скрипт
печатает готовую ссылку и команду для ручного шага.

Использование:
  python3 .github/scripts/db_schema.py            # пересобрать db.sql
  python3 .github/scripts/db_schema.py --check     # проверить актуальность (код 1 при расхождении)
  python3 .github/scripts/db_schema.py --render    # пересобрать db.sql и schema.png
  python3 .github/scripts/db_schema.py --url       # только напечатать share-ссылку

Зависимости — стандартная библиотека Python 3.11+.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import zlib
from pathlib import Path
from urllib.parse import urlparse

from yaml_subset import YamlSubset, YamlSubsetError

CHANGELOG_DIR = "backend/api/src/main/resources/db/changelog"
MASTER = CHANGELOG_DIR + "/db.changelog-master.yaml"
DB_SQL = "documentation/design/db.sql"
ERD_PNG = "documentation/design/schema.png"

SITE = "https://sqltoerdiagram.com/"
CHROME_IMAGE = "zenika/alpine-chrome:latest"
CONTAINER = "docsapp-erd"
POSTGRES_IMAGE = "postgres:16-alpine"
PG_CONTAINER = "docsapp-dbcheck"
ERD_WINDOW = (1600, 1200)
ERD_SCALE = 2

HEADER = """-- DocsApp: схема базы данных.
--
-- Файл сгенерирован из Liquibase-чанжлога {changelog}/
-- Пересобрать: `make db-schema`. ERD: {erd} (`make db-erd`).
-- Руками не правим: правки перезапишутся, менять нужно чанжлог.
--
-- Состав:
{parts}
"""


def git_repo_root(start: Path) -> Path:
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=str(start),
                             capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return start.resolve()
    return Path(out)


def is_true(value) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "on"}


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


LIQUIBASE_DIRECTIVE = ("liquibase", "changeset", "changeSet", "rollback", "preconditions",
                       "comment", "property", "validCheckSum")


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
            if directive in {name.lower() for name in LIQUIBASE_DIRECTIVE}:
                continue
        lines.append(reindent(line.rstrip()))

    result: list[str] = []
    for line in lines:
        if line or (result and result[-1]):
            result.append(line)
    while result and not result[-1]:
        result.pop()
    return "\n".join(result)


def build(root: Path) -> tuple[str, list[str]]:
    files, warnings = load_changelog(root)
    if not files:
        raise SystemExit("Чанжлог не содержит SQL-файлов — собирать нечего")

    parts = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        try:
            sql = clean_sql(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            warnings.append("%s не читается: %s" % (rel, exc))
            continue
        lines = len(sql.splitlines())
        parts.append((rel, sql, lines))

    listing = "\n".join("--   %s — %d %s" % (rel, lines, "строка" if lines % 10 == 1 and lines % 100 != 11
                                             else "строки" if 2 <= lines % 10 <= 4 and not 12 <= lines % 100 <= 14
                                             else "строк")
                       for rel, _, lines in parts)
    header = HEADER.format(changelog=CHANGELOG_DIR, erd=ERD_PNG, parts=listing)
    body = "\n\n".join(sql for _, sql, _ in parts)
    return header + "\n" + body + "\n", warnings


def share_url(sql: str) -> str:
    """Share-ссылка sqltoerdiagram.com: `#s=` + deflate-raw + base64url от JSON."""
    payload = json.dumps({"sql": sql}, ensure_ascii=False).encode("utf-8")
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    packed = compressor.compress(payload) + compressor.flush()
    encoded = base64.urlsafe_b64encode(packed).decode("ascii").rstrip("=")
    return "%s?embed#s=z%s" % (SITE, encoded)


class CdpError(RuntimeError):
    """Не удалось поговорить с headless-браузером."""


def ws_connect(url: str, timeout: float = 10.0):
    """Минимальный WebSocket-клиент (RFC 6455) — DevTools работает только по нему."""
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    sock = socket.create_connection((host, port), timeout)
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    sock.sendall(("GET %s HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\n"
                  "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\n"
                  "Sec-WebSocket-Version: 13\r\n\r\n" % (path, host, port, key)).encode("ascii"))
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            raise CdpError("рукопожатие WebSocket прервано")
        data += chunk
    if b" 101 " not in data.split(b"\r\n", 1)[0]:
        raise CdpError("WebSocket не подтвердил переключение протокола")
    return sock


def ws_send(sock, payload: bytes, opcode: int = 1) -> None:
    header = bytes([0x80 | opcode])
    mask = os.urandom(4)
    length = len(payload)
    if length < 126:
        header += bytes([0x80 | length])
    elif length < 65536:
        header += bytes([0x80 | 126]) + length.to_bytes(2, "big")
    else:
        header += bytes([0x80 | 127]) + length.to_bytes(8, "big")
    sock.sendall(header + mask + bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload)))


def ws_receive(sock) -> tuple[int, bytes]:
    def read_exact(count: int) -> bytes:
        buffer = b""
        while len(buffer) < count:
            chunk = sock.recv(count - len(buffer))
            if not chunk:
                raise CdpError("соединение с браузером закрыто")
            buffer += chunk
        return buffer

    first, second = read_exact(2)
    opcode = first & 0x0F
    length = second & 0x7F
    if length == 126:
        length = int.from_bytes(read_exact(2), "big")
    elif length == 127:
        length = int.from_bytes(read_exact(8), "big")
    mask = read_exact(4) if second & 0x80 else None
    payload = read_exact(length)
    if mask:
        payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    return opcode, payload


class DevTools:
    """Клиент Chrome DevTools Protocol: вызвать JS в странице и забрать результат."""

    def __init__(self, url: str):
        self.sock = ws_connect(url)
        self.next_id = 0

    def call(self, method: str, params: dict | None = None, timeout_ms: int = 120_000):
        self.next_id += 1
        message = {"id": self.next_id, "method": method, "params": params or {}}
        ws_send(self.sock, json.dumps(message).encode("utf-8"))
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            opcode, payload = ws_receive(self.sock)
            if opcode == 8:
                raise CdpError("браузер закрыл соединение")
            if opcode == 9:
                ws_send(self.sock, payload, opcode=10)
                continue
            if opcode != 1:
                continue
            answer = json.loads(payload.decode("utf-8"))
            if answer.get("id") != self.next_id:
                continue
            if "error" in answer:
                raise CdpError(str(answer["error"]))
            return answer.get("result")
        raise CdpError("нет ответа на %s" % method)

    def evaluate(self, expression: str, await_promise: bool = False):
        result = self.call("Runtime.evaluate", {
            "expression": expression,
            "awaitPromise": await_promise,
            "returnByValue": True,
        })
        if result.get("exceptionDetails"):
            raise CdpError(str(result["exceptionDetails"]).replace("\n", " ")[:300])
        return result.get("result", {}).get("value")

    def close(self) -> None:
        try:
            ws_send(self.sock, b"", opcode=8)
        except OSError:
            pass
        self.sock.close()


def page_websocket(port: int, timeout: float = 40.0) -> str:
    """Ждёт, пока headless-браузер поднимет страницу, и отдаёт WebSocket страницы."""
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/json" % port, timeout=3) as response:
                targets = json.loads(response.read().decode("utf-8"))
            pages = [t for t in targets if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
            if pages:
                return pages[0]["webSocketDebuggerUrl"]
            last = "страниц нет"
        except (OSError, ValueError) as exc:
            last = str(exc)
        time.sleep(0.5)
    raise CdpError("браузер не поднялся: %s" % last)


def chromium_container(url: str, port: int) -> list[str]:
    return ["docker", "run", "--rm", "--init", "--name", CONTAINER, "--network", "host",
            CHROME_IMAGE,
            "--headless", "--no-sandbox", "--no-zygote", "--disable-setuid-sandbox",
            "--disable-dev-shm-usage", "--disable-gpu", "--hide-scrollbars",
            "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
            "--remote-debugging-address=0.0.0.0", "--remote-debugging-port=%d" % port,
            "--window-size=%d,%d" % ERD_WINDOW, url]


WAIT_LAYOUT_JS = """(() => {
  const busy = document.querySelector('.busy-chip');
  const renderer = window.__dbdiga;
  const tables = renderer && renderer.model ? renderer.model.tables.length : 0;
  return {ready: (!busy || busy.hidden) && tables > 0, tables};
})()"""

EXPORT_JS = """(async () => {
  const renderer = window.__dbdiga;
  if (!renderer || typeof renderer.exportPNG !== 'function') return null;
  return renderer.exportPNG(%d);
})()"""


def verify(sql_path: Path, dry_run: bool) -> int:
    """Прогоняет db.sql на чистой PostgreSQL в docker: черновик схемы должен хотя бы выполняться."""
    if not shutil.which("docker"):
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


def render(url: str, target: Path, dry_run: bool) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    if not shutil.which("docker"):
        print("Нет docker с образом %s — картинку не снять." % CHROME_IMAGE, file=sys.stderr)
        print("Откройте %s и сохраните PNG в %s." % (url, target), file=sys.stderr)
        return 1

    port = 9222
    command = chromium_container(url, port)
    if dry_run:
        print(" ".join(command))
        return 0

    print("Рисую ERD через %s (headless chromium, docker)…" % SITE, flush=True)
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    devtools = None
    try:
        devtools = DevTools(page_websocket(port))
        devtools.call("Runtime.enable")
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            state = devtools.evaluate(WAIT_LAYOUT_JS)
            if isinstance(state, dict) and state.get("ready"):
                break
            time.sleep(0.5)
        else:
            raise CdpError("схема не разложилась за 90 с")

        time.sleep(1.0)  # шрифты и финальная отрисовка
        data_url = devtools.evaluate(EXPORT_JS % ERD_SCALE, await_promise=True)
        if not isinstance(data_url, str) or "," not in data_url:
            raise CdpError("сайт не отдал PNG")
        target.write_bytes(base64.b64decode(data_url.split(",", 1)[1]))
        print("ERD: %s (%d КБ)" % (target, target.stat().st_size // 1024))
        return 0
    except CdpError as exc:
        print("Не удалось снять ERD: %s" % exc, file=sys.stderr)
        print("Откройте вручную: %s" % url, file=sys.stderr)
        return 1
    finally:
        if devtools is not None:
            devtools.close()
        process.terminate()
        subprocess.run(["docker", "rm", "-f", CONTAINER],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DDL и ERD из Liquibase-чанжлога")
    parser.add_argument("--root", default=".", help="корень репозитория")
    parser.add_argument("--check", action="store_true",
                        help="не писать db.sql, а проверить, что он совпадает с чанжлогом")
    parser.add_argument("--render", action="store_true", help="перерисовать schema.png")
    parser.add_argument("--verify", action="store_true",
                        help="прогнать db.sql на чистой PostgreSQL в docker")
    parser.add_argument("--url", action="store_true", help="только напечатать share-ссылку")
    parser.add_argument("--print-command", action="store_true",
                        help="показать команду снимка, ничего не запуская")
    args = parser.parse_args(argv)

    root = git_repo_root(Path(args.root).resolve())
    sql, warnings = build(root)
    for warning in dict.fromkeys(warnings):
        print("⚠ %s" % warning, file=sys.stderr)

    if args.url:
        print(share_url(sql))
        return 0

    target = root / DB_SQL
    if args.check:
        current = target.read_text(encoding="utf-8") if target.is_file() else ""
        if current != sql:
            print("%s расходится с чанжлогом." % DB_SQL)
            print("Пересоберите: make db-schema")
            return 1
        print("%s соответствует чанжлогу (%d строк)" % (DB_SQL, len(sql.splitlines())))
        return 0

    if target.is_file() and target.read_text(encoding="utf-8") == sql:
        print("%s уже актуален (%d строк)" % (DB_SQL, len(sql.splitlines())))
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(sql, encoding="utf-8")
        print("%s пересобран из чанжлога (%d строк)" % (DB_SQL, len(sql.splitlines())))

    if args.verify:
        return verify(target, dry_run=args.print_command)
    if args.render:
        return render(share_url(sql), root / ERD_PNG, dry_run=args.print_command)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
