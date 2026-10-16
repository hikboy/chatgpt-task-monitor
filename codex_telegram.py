#!/usr/bin/env python3
"""Codex turn-completion notifications for Windows, macOS and Linux.

Python 3.11+, standard library only. Native callbacks stay quiet and never
fail a Codex turn; interactive commands report a nonzero status on failure.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime
import getpass
import html
import json
import os
from pathlib import Path
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import tomllib
import urllib.error
import urllib.request

VERSION = "1.1.1"
IS_WINDOWS = sys.platform == "win32"
INSTALL_SUBDIR = Path("notifications") / "codex-telegram"
SOURCE = Path(__file__).resolve()
TOKEN_PATTERN = re.compile(r"\d+:[A-Za-z0-9_-]{20,}\Z")
CHAT_PATTERN = re.compile(r"(?:-?\d+|@[A-Za-z0-9_]{5,})\Z")
SAFE_CODES = {
    "invalid-event", "missing-telegram-settings", "invalid-telegram-settings",
    "invalid-settings-file", "telegram-request-failed", "telegram-rejected-message",
    "original-callback-unavailable", "original-callback-start-failed",
    "original-callback-invalid", "notification-unexpected-error",
}


class NotificationError(Exception):
    """An error code that is safe to show or log without leaking credentials."""


def codex_home(value: str | None = None) -> Path:
    return Path(value or os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser().resolve()


def managed_dir(home: Path) -> Path:
    return home / INSTALL_SUBDIR


def atomic_write(path: Path, data: bytes, *, private: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if not IS_WINDOWS:
            os.chmod(temporary_path, 0o600 if private else 0o644)
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def write_json(path: Path, value: object, *, private: bool = False) -> None:
    atomic_write(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"), private=private)


def log_code(home: Path, code: str) -> None:
    if code not in SAFE_CODES:
        code = "notification-unexpected-error"
    try:
        target = managed_dir(home) / "error.log"
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with target.open("a", encoding="utf-8") as stream:
            stream.write(f"{datetime.now().astimezone().isoformat()} {code}\n")
    except OSError:
        pass


def excerpt(value: object, length: int, fallback: str = "") -> str:
    if not isinstance(value, str):
        return fallback
    text = " ".join(value.split())
    if not text:
        return fallback
    # Python slices Unicode code points, so UTF-16 surrogate pairs aren't split.
    return text if len(text) <= length else text[:length - 1].rstrip() + "…"


def plain_markdown(text: str) -> str:
    """Clean common Markdown decorations without interpreting raw HTML."""
    text = re.sub(r"!?\[([^\]\n]*)\]\([^\n]*?\)", r"\1", text)
    text = re.sub(r"`+([^`\n]+)`+", r"\1", text)
    for marker in (r"\*\*", "__", "~~"):
        text = re.sub(marker + r"(.+?)" + marker, r"\1", text, flags=re.DOTALL)
    text = re.sub(r"(?<!\w)\*([^*\n]+)\*(?!\w)", r"\1", text)
    text = re.sub(r"(?<!\w)_([^_\n]+)_(?!\w)", r"\1", text)
    text = re.sub(r"(?m)^[ \t]{0,3}#{1,6}[ \t]+", "", text)
    text = re.sub(r"(?m)^[ \t]*>[ \t]?", "", text)
    text = re.sub(r"(?m)^[ \t]*[-+*][ \t]+", "• ", text)
    lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def readable_excerpt(text: str, length: int) -> str:
    """Truncate plain text before HTML escaping, preferring complete sentences."""
    if len(text) <= length:
        return text
    shortened = text[:length - 1].rstrip()
    endings = list(re.finditer(r"[。！？]|[.!?](?=\s|$)", shortened))
    if endings and endings[-1].end() >= length // 2:
        shortened = shortened[:endings[-1].end()]
    return shortened + "…"


def table_separator(line: str) -> bool:
    cells = line.strip().strip("|").split("|")
    return len(cells) >= 2 and all(re.fullmatch(r"\s*:?-{3,}:?\s*", cell) for cell in cells)


def result_preview(value: object) -> tuple[str, list[str]]:
    """Keep the opening prose, with notices for omitted tables and fenced code."""
    if not isinstance(value, str) or not value.strip():
        return "未提供结果内容", []
    lines = value.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    prose = []
    has_table = has_code = False
    fence = ""
    index = 0
    while index < len(lines):
        line = lines[index]
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence):
                fence = ""
            index += 1
            continue
        if marker:
            has_code = True
            fence = marker[1]
            prose.append("")
            index += 1
            continue
        if "|" in line and index + 1 < len(lines) and table_separator(lines[index + 1]):
            has_table = True
            prose.append("")
            index += 2
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                index += 1
            continue
        if re.fullmatch(r"\s*(?:\*\s*){3,}|\s*(?:-\s*){3,}|\s*(?:_\s*){3,}", line):
            prose.append("")
        else:
            prose.append(line)
        index += 1
    cleaned = plain_markdown("\n".join(prose))
    paragraphs = re.split(r"\n\s*\n", cleaned) if cleaned else []
    summary = readable_excerpt("\n\n".join(paragraphs[:2]), 300) if paragraphs else "回复内容见会话。"
    notes = []
    if has_table:
        notes.append("📋 回复包含对比表，详情见会话。")
    if has_code:
        notes.append("🧩 回复包含代码，详情见会话。")
    if len(paragraphs) > 2 and not notes:
        notes.append("更多内容见会话。")
    return summary, notes


def resolve_session_name(event: dict, home: Path) -> str:
    provided = excerpt(event.get("thread-name"), 2000)
    if provided:
        return provided
    thread_id = event.get("thread-id")
    if not isinstance(thread_id, str) or not thread_id.strip():
        return "未提供会话信息"

    fallback_title = ""
    # New desktop versions keep explicit names in SQLite. Read-only and bound
    # parameters avoid changing the app database or interpreting the ID as SQL.
    databases = [path for path in home.glob("state_*.sqlite") if re.fullmatch(r"state_\d+\.sqlite", path.name)]
    databases.sort(key=lambda path: int(re.search(r"state_(\d+)", path.name)[1]), reverse=True)
    for database in databases:
        try:
            with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.25)) as connection:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(threads)")}
                if "name" in columns:
                    row = connection.execute("SELECT name, title FROM threads WHERE id = ?", (thread_id,)).fetchone()
                    if row:
                        name = excerpt(row[0], 2000)
                        if name:
                            return name
                        fallback_title = fallback_title or excerpt(row[1], 2000)
                elif "title" in columns:
                    row = connection.execute("SELECT title FROM threads WHERE id = ?", (thread_id,)).fetchone()
                    if row:
                        fallback_title = fallback_title or excerpt(row[0], 2000)
        except (OSError, sqlite3.Error):
            continue

    latest = ""
    try:
        with (home / "session_index.jsonl").open(encoding="utf-8-sig") as stream:
            for line in stream:
                try:
                    entry = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if isinstance(entry, dict) and entry.get("id") == thread_id:
                    latest = excerpt(entry.get("thread_name"), 2000)
    except OSError:
        pass
    return latest or fallback_title or f"未命名会话（{thread_id}）"


def build_message(event: dict, home: Path) -> tuple[str, dict]:
    name = resolve_session_name(event, home)
    inputs = event.get("input-messages", [])
    if isinstance(inputs, str):
        inputs = [inputs]
    if not isinstance(inputs, list):
        inputs = []
    tasks = [" ".join(plain_markdown(item).split()) for item in inputs if isinstance(item, str) and item.strip()]
    task = readable_excerpt("；".join(item for item in tasks if item), 150) or "未提供任务内容"
    result, notes = result_preview(event.get("last-assistant-message"))
    hostname = excerpt(socket.gethostname(), 80, "未知电脑")
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    escape = html.escape
    message = (
        "✅ <b>本轮任务完成</b>\n\n"
        f"📌 <b>会话：</b> {escape(excerpt(name, 200))}\n\n"
        f"📝 <b>任务</b>\n{escape(task)}\n\n"
        f"💡 <b>结果</b>\n{escape(result)}"
    )
    if notes:
        message += "\n\n" + "\n".join(f"<i>{escape(note)}</i>" for note in notes)
    message += f"\n\n💻 {escape(hostname)}\n🕒 {escape(timestamp)}"
    return message, {"session_name": name, "task_summary": task, "result_summary": result}


def windows_setting(name: str) -> str:
    if not IS_WINDOWS:
        return ""
    import winreg
    locations = [
        (winreg.HKEY_CURRENT_USER, "Environment"),
        (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
    ]
    for hive, key in locations:
        try:
            with winreg.OpenKey(hive, key) as handle:
                value, _ = winreg.QueryValueEx(handle, name)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        except OSError:
            continue
    return ""


def credential_values(home: Path) -> tuple[str, str]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    settings = managed_dir(home) / "settings.json"
    if (not token or not chat_id) and settings.exists():
        try:
            saved = json.loads(settings.read_text(encoding="utf-8-sig"))
            if not isinstance(saved, dict):
                raise ValueError
            token = token or str(saved.get("bot_token", "")).strip()
            chat_id = chat_id or str(saved.get("chat_id", "")).strip()
        except (OSError, ValueError):
            raise NotificationError("invalid-settings-file") from None
    return token or windows_setting("TELEGRAM_BOT_TOKEN"), chat_id or windows_setting("TELEGRAM_CHAT_ID")


def validate_credentials(token: str, chat_id: str) -> None:
    if not token or not chat_id:
        raise NotificationError("missing-telegram-settings")
    if not TOKEN_PATTERN.fullmatch(token) or not CHAT_PATTERN.fullmatch(chat_id):
        raise NotificationError("invalid-telegram-settings")


def send_telegram(home: Path, message: str) -> None:
    token, chat_id = credential_values(home)
    validate_credentials(token, chat_id)
    body = json.dumps({"chat_id": chat_id, "text": message, "parse_mode": "HTML"}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body,
                                     headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            reply = json.loads(response.read(1024 * 1024))
    except (OSError, ValueError, urllib.error.URLError):
        raise NotificationError("telegram-request-failed") from None
    if not isinstance(reply, dict) or reply.get("ok") is not True:
        raise NotificationError("telegram-rejected-message")


def valid_command(value: object) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(item, str) and item for item in value)


def own_command(command: list[str], home: Path) -> bool:
    targets = {SOURCE, (managed_dir(home) / "codex_telegram.py").resolve()}
    return any(Path(argument).expanduser().resolve() in targets for argument in command if argument.endswith(".py"))


def legacy_script(command: list[str]) -> Path | None:
    for argument in command:
        candidate = Path(argument)
        if candidate.name.lower() == "codex-telegram.ps1" and (candidate.parent / "codex-original-notify.json").is_file():
            return candidate
    return None


def desktop_previous(command: list[str]) -> list[tuple[int, list[str]]]:
    if Path(command[0]).name.lower() not in {"codex-computer-use", "codex-computer-use.exe"} or "turn-ended" not in command:
        return []
    callbacks = []
    for index, argument in enumerate(command[:-1]):
        if argument == "--previous-notify":
            try:
                nested = json.loads(command[index + 1])
            except ValueError:
                continue
            if valid_command(nested):
                callbacks.append((index, nested))
    return callbacks


def contains_own_command(command: list[str], home: Path, depth: int = 0) -> bool:
    if depth > 8:
        return True  # Do not forward an unexpectedly recursive callback chain.
    return own_command(command, home) or legacy_script(command) is not None or any(
        contains_own_command(nested, home, depth + 1) for _, nested in desktop_previous(command)
    )


def sanitize_original(command: list[str], home: Path) -> list[str]:
    # The desktop app can wrap our earlier notifier with its own turn-ended
    # command. Keep that desktop command but remove its link back to us.
    result = list(command)
    for index, nested in reversed(desktop_previous(command)):
        if contains_own_command(nested, home):
            del result[index:index + 2]
    return result


def resolve_executable(value: str) -> str:
    executable = Path(value).expanduser()
    if executable.is_file():
        return str(executable)
    found = shutil.which(value)
    if found:
        return found
    if IS_WINDOWS and os.environ.get("LOCALAPPDATA"):
        runtime_root = Path(os.environ["LOCALAPPDATA"]) / "OpenAI/Codex/runtimes/cua_node"
        try:
            relative = executable.relative_to(runtime_root)
            suffix = Path(*relative.parts[1:])
            for runtime in sorted(runtime_root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
                candidate = runtime / suffix
                if candidate.is_file():
                    return str(candidate)
        except (OSError, ValueError):
            pass
    return ""


def forward_original(home: Path, event_json: str) -> None:
    saved = managed_dir(home) / "codex-original-notify.json"
    if not saved.exists():
        return
    try:
        command = json.loads(saved.read_text(encoding="utf-8-sig"))
        if command == []:
            return
        if not valid_command(command) or contains_own_command(command, home):
            raise NotificationError("original-callback-invalid")
        executable = resolve_executable(command[0])
        if not executable:
            raise NotificationError("original-callback-unavailable")
        options = {"creationflags": 0x08000000} if IS_WINDOWS else {"start_new_session": True}
        subprocess.Popen([executable, *command[1:], event_json], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, **options)
    except NotificationError as error:
        log_code(home, str(error))
    except (OSError, ValueError, TypeError):
        log_code(home, "original-callback-start-failed")


def notify(event_json: str, home: Path, *, dry_run: bool = False, skip_original: bool = False) -> dict:
    result = {"success": False, "status": "failed"}
    try:
        try:
            event = json.loads(event_json)
        except (TypeError, ValueError):
            raise NotificationError("invalid-event") from None
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            raise NotificationError("invalid-event")
        if not dry_run and not skip_original:
            forward_original(home, event_json)
        if event["type"] != "agent-turn-complete":
            return {"success": True, "status": "skipped"}
        message, details = build_message(event, home)
        result.update(details)
        if dry_run:
            result.update(success=True, status="dry-run", message=message)
        else:
            send_telegram(home, message)
            result.update(success=True, status="sent")
    except NotificationError as error:
        result["status"] = str(error)
        log_code(home, str(error))
    except Exception:
        result["status"] = "notification-unexpected-error"
        log_code(home, result["status"])
    return result


def replace_notify(config: str, command: list[str]) -> str:
    """Use tomllib to locate complete assignments without reformatting TOML."""
    parsed = tomllib.loads(config)
    newline = "\r\n" if "\r\n" in config else "\n"
    replacement = "notify = " + json.dumps(command, ensure_ascii=False) + newline
    if "notify" not in parsed:
        return replacement + newline + config
    if not valid_command(parsed["notify"]) and parsed["notify"] != []:
        raise ValueError("The existing notify setting must be an array of strings.")
    lines = config.splitlines(keepends=True)
    for start, line in enumerate(lines):
        if not re.match(r'''^\s*(?:notify|"notify"|'notify')\s*=''', line):
            continue
        try:
            prefix = tomllib.loads("".join(lines[:start]))
        except tomllib.TOMLDecodeError:
            continue  # A matching line inside a multiline TOML string.
        if "notify" in prefix:
            continue
        for end in range(start + 1, len(lines) + 1):
            try:
                candidate = tomllib.loads("".join(lines[:end]))
            except tomllib.TOMLDecodeError:
                continue
            if "notify" in candidate:
                return "".join(lines[:start]) + replacement + "".join(lines[end:])
            break  # A nested table key, not the top-level notify setting.
    raise ValueError("Could not safely locate the existing top-level notify setting.")


def previous_command(current: list[str], home: Path) -> list[str]:
    if own_command(current, home):
        saved = managed_dir(home) / "codex-original-notify.json"
        value = json.loads(saved.read_text(encoding="utf-8-sig")) if saved.exists() else []
    else:
        value = current
        # Migrate our earlier PowerShell implementation without forwarding to
        # it and accidentally sending each Telegram notification twice.
        legacy = legacy_script(current)
        if legacy is not None:
            value = json.loads((legacy.parent / "codex-original-notify.json").read_text(encoding="utf-8-sig"))
    if value != [] and not valid_command(value):
        raise ValueError("The saved original notification command is invalid.")
    return sanitize_original(value, home) if value else []


def install(home: Path) -> dict:
    config_path = home / "config.toml"
    original_bytes = config_path.read_bytes() if config_path.exists() else b""
    original_text = original_bytes.decode("utf-8-sig")
    current = tomllib.loads(original_text).get("notify", [])
    if current != [] and not valid_command(current):
        raise ValueError("The existing notify setting is invalid.")
    original_callback = previous_command(current, home)
    destination = managed_dir(home) / "codex_telegram.py"
    executable = Path(sys.executable).resolve()
    hidden_executable = executable.with_name("pythonw.exe")
    notification_python = hidden_executable if IS_WINDOWS and hidden_executable.is_file() else executable
    command = [str(notification_python), str(destination), "--codex-home", str(home), "notify"]
    updated = replace_notify(original_text, command)
    tomllib.loads(updated)
    backup = None
    if original_bytes:
        backup = home / ("config.toml.backup-telegram-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
        atomic_write(backup, original_bytes, private=True)
    if SOURCE != destination.resolve():
        atomic_write(destination, SOURCE.read_bytes())
    for name in ("README.md", "codex-telegram.ps1"):
        source = SOURCE.parent / name
        target = managed_dir(home) / name
        if source.is_file() and source.resolve() != target.resolve():
            atomic_write(target, source.read_bytes())
    write_json(managed_dir(home) / "codex-original-notify.json", original_callback)
    write_json(managed_dir(home) / "runtime.json", {"python": str(executable)})
    atomic_write(config_path, updated.encode("utf-8"), private=True)
    return {"success": True, "status": "installed", "version": VERSION, "script": str(destination),
            "config": str(config_path), "backup": str(backup) if backup else None, "notify": command,
            "restart_required": True}


def test_event(session_id: str | None = None) -> str:
    return json.dumps({"type": "agent-turn-complete", "thread-id": session_id,
                       "thread-name": None if session_id else "通知测试",
                       "input-messages": ["跨平台 Telegram 通知测试"],
                       "last-assistant-message": "这是一条测试通知：包含会话名称、任务摘要、结果摘要、电脑名和完成时间。"}, ensure_ascii=False)


def configure(home: Path, send_test: bool) -> dict:
    if not sys.stdin.isatty():
        raise ValueError("Run configure in an interactive terminal.")
    old_token, old_chat = credential_values(home)
    token = getpass.getpass("Telegram Bot Token (hidden; Enter keeps existing): ").strip() or old_token
    chat_id = input(f"Telegram Chat ID [{old_chat}]: ").strip() or old_chat
    validate_credentials(token, chat_id)
    target = managed_dir(home) / "settings.json"
    write_json(target, {"bot_token": token, "chat_id": chat_id}, private=True)
    result = {"success": True, "status": "configured", "settings": str(target)}
    if send_test:
        # Test exactly what was entered, even if the launching terminal still
        # contains older environment variables.
        os.environ.update(TELEGRAM_BOT_TOKEN=token, TELEGRAM_CHAT_ID=chat_id)
        result["test"] = notify(test_event(), home, skip_original=True)
        result["success"] = result["test"]["success"]
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", help="Defaults to CODEX_HOME or ~/.codex")
    parser.add_argument("--version", action="version", version=VERSION)
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("install", help="Install and update the user-level Codex notify setting")
    setup = subcommands.add_parser("configure", help="Save Telegram credentials interactively")
    setup.add_argument("--test", action="store_true", help="Send one test notification after saving")
    callback = subcommands.add_parser("notify", help="Handle the JSON event appended by Codex")
    callback.add_argument("event", nargs="?")
    callback.add_argument("--stdin", action="store_true", help="Read UTF-8 JSON from stdin")
    callback.add_argument("--dry-run", action="store_true")
    callback.add_argument("--skip-original", action="store_true")
    callback.add_argument("--json", action="store_true", help="Print a diagnostic result")
    test = subcommands.add_parser("test", help="Send a test message; does not invoke the original callback")
    test.add_argument("--session-id")
    test.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    home = codex_home(args.codex_home)
    try:
        if args.command == "install":
            result = install(home)
        elif args.command == "configure":
            result = configure(home, args.test)
        elif args.command == "test":
            result = notify(test_event(args.session_id), home, dry_run=args.dry_run, skip_original=True)
        else:
            event_json = sys.stdin.buffer.read().decode("utf-8-sig") if args.stdin else args.event
            result = notify(event_json, home, dry_run=args.dry_run, skip_original=args.skip_original)
    except NotificationError as error:
        result = {"success": False, "status": str(error)}
    except (OSError, ValueError):
        result = {"success": False, "status": "configuration-failed"}
    if args.command != "notify" or args.json or args.dry_run:
        if sys.stdout is not None:
            print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if args.command == "notify" or result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
