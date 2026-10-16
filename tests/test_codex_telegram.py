import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest import mock
import urllib.error
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import codex_telegram as notifier

TOKEN = "123456:" + "a" * 30
CHAT = "-123456789"


class NotificationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name) / "codex home 空格"
        self.home.mkdir()
        self.addCleanup(mock.patch.stopall)
        mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""}).start()
        mock.patch.object(notifier, "windows_setting", return_value="").start()

    def event(self, **changes):
        event = {"type": "agent-turn-complete", "thread-id": "session-1",
                 "input-messages": ["测试任务"], "last-assistant-message": "测试结果"}
        event.update(changes)
        return json.dumps(event, ensure_ascii=False)

    def index(self, entries):
        (self.home / "session_index.jsonl").write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in entries), encoding="utf-8")

    def save_credentials(self):
        notifier.write_json(notifier.managed_dir(self.home) / "settings.json",
                            {"bot_token": TOKEN, "chat_id": CHAT}, private=True)

    def database(self, with_name=True):
        database = self.home / "state_5.sqlite"
        connection = sqlite3.connect(database)
        if with_name:
            connection.execute("CREATE TABLE threads (id TEXT, name TEXT, title TEXT)")
            connection.execute("INSERT INTO threads VALUES (?, ?, ?)", ("session-1", "数据库中的新名称", "初始问题"))
        else:
            connection.execute("CREATE TABLE threads (id TEXT, title TEXT)")
            connection.execute("INSERT INTO threads VALUES (?, ?)", ("session-1", "数据库初始标题"))
        connection.commit()
        connection.close()
        return database

    def test_latest_session_rename_and_unrelated_session(self):
        self.index([{"id": "session-1", "thread_name": "旧名称"},
                    {"id": "another", "thread_name": "其他会话"},
                    {"id": "session-1", "thread_name": "监控 PowerShell 😀"}])
        with (self.home / "session_index.jsonl").open("a", encoding="utf-8") as stream:
            stream.write("\n{incomplete")
        result = notifier.notify(self.event(), self.home, dry_run=True)
        self.assertEqual(result["session_name"], "监控 PowerShell 😀")

    def test_database_name_takes_precedence_over_stale_index(self):
        self.database()
        self.index([{"id": "session-1", "thread_name": "索引中的旧名称"}])
        self.assertEqual(notifier.notify(self.event(), self.home, dry_run=True)["session_name"], "数据库中的新名称")

    def test_older_database_title_does_not_hide_explicit_index_name(self):
        self.database(with_name=False)
        self.index([{"id": "session-1", "thread_name": "手动命名"}])
        self.assertEqual(notifier.notify(self.event(), self.home, dry_run=True)["session_name"], "手动命名")
        (self.home / "session_index.jsonl").unlink()
        self.assertEqual(notifier.notify(self.event(), self.home, dry_run=True)["session_name"], "数据库初始标题")

    def test_corrupt_or_unknown_database_falls_back_to_index(self):
        (self.home / "state_9.sqlite").write_bytes(b"not a database")
        (self.home / "state_unrecognized.sqlite").write_bytes(b"ignored")
        self.index([{"id": "session-1", "thread_name": "正常名称"}])
        self.assertEqual(notifier.notify(self.event(), self.home, dry_run=True)["session_name"], "正常名称")

    def test_missing_session_and_optional_fields(self):
        result = notifier.notify(self.event(**{"input-messages": None, "last-assistant-message": None}), self.home, dry_run=True)
        self.assertIn("session-1", result["session_name"])
        self.assertEqual(result["task_summary"], "未提供任务内容")
        self.assertEqual(result["result_summary"], "未提供结果内容")

    def test_summaries_unicode_whitespace_and_message_size(self):
        result = notifier.notify(self.event(**{"input-messages": [" 第一条\n任务 ", "", "追加要求 😀"],
                                               "last-assistant-message": "结果\n\t成功"}), self.home, dry_run=True)
        self.assertEqual(result["task_summary"], "第一条 任务；追加要求 😀")
        self.assertEqual(result["result_summary"], "结果\n成功")
        long = notifier.notify(self.event(**{"input-messages": ["😀" * 1000],
                                             "last-assistant-message": "结果" * 1000}), self.home, dry_run=True)
        self.assertEqual(len(long["task_summary"]), 150)
        self.assertEqual(len(long["result_summary"]), 300)
        self.assertTrue(long["task_summary"].endswith("…"))
        self.assertLessEqual(len(long["message"].encode("utf-16-le")) // 2, 4096)
        long["message"].encode("utf-8", errors="strict")

    def test_single_string_input_and_html_escaping(self):
        result = notifier.notify(self.event(**{"thread-name": '<b>Session & "name"</b>',
                                               "input-messages": "a < b & [x]", "last-assistant-message": "`snake_case` < limit & **成功**"}), self.home, dry_run=True)
        self.assertEqual(result["task_summary"], "a < b & [x]")
        self.assertEqual(result["result_summary"], "snake_case < limit & 成功")
        self.assertIn("📝 <b>Task</b>\na &lt; b &amp; [x]", result["message"])
        self.assertIn("&lt;b&gt;Session &amp; &quot;name&quot;&lt;/b&gt;", result["message"])
        tree = ElementTree.fromstring("<root>" + result["message"] + "</root>")
        self.assertTrue(all(element.tag in {"root", "b", "i"} for element in tree.iter()))
        self.assertIn('<b>Session & "name"</b>', "".join(tree.itertext()))

    def test_section_layout_and_explicit_failure_status(self):
        result = notifier.notify(self.event(**{"thread-name": "排版测试"}), self.home, dry_run=True)
        self.assertTrue(result["message"].startswith("✅ <b>Success</b>\n\n"))
        self.assertIn("📌 <b>Session</b>\n排版测试\n\n📝 <b>Task</b>\n测试任务\n\n💡 <b>Result</b>\n测试结果", result["message"])
        self.assertEqual(result["completion_status"], "success")
        failed = notifier.notify(self.event(**{"notification-status": "failed"}), self.home, dry_run=True)
        self.assertTrue(failed["message"].startswith("❌ <b>Failed</b>\n\n"))
        self.assertEqual(failed["completion_status"], "failed")
        self.assertTrue(failed["success"])  # Successful preview of a reported failure.
        ambiguous = notifier.notify(self.event(**{"last-assistant-message": "解释 Failed 标签，并举例说明测试失败。"}), self.home, dry_run=True)
        self.assertEqual(ambiguous["completion_status"], "success")
        for invalid in ("unknown", None, False, {}):
            with self.subTest(invalid=invalid):
                self.assertEqual(notifier.notify(self.event(**{"notification-status": invalid}), self.home, dry_run=True)["status"], "invalid-event")

    def test_result_summary_retains_three_points_beyond_opening_paragraphs(self):
        reply = "完成摘要。\n\n补充说明。\n\n1. 第一项\n\n2) 第二项\n继续说明\n\n- 第三项\n- 第四项"
        result = notifier.notify(self.event(**{"last-assistant-message": reply}), self.home, dry_run=True)
        self.assertEqual(result["result_summary"], "完成摘要。\n\n补充说明。\n\n• 第一项\n• 第二项 继续说明\n• 第三项")
        self.assertNotIn("第四项", result["message"])
        self.assertIn("更多内容见会话。", result["message"])
        long = "摘要" * 200 + "\n\n" + "\n".join("- " + "😀" * 100 for _ in range(4))
        result = notifier.notify(self.event(**{"last-assistant-message": long}), self.home, dry_run=True)
        self.assertLessEqual(len(result["result_summary"]), 300)
        self.assertEqual(result["result_summary"].count("• "), 3)
        ElementTree.fromstring("<root>" + result["message"] + "</root>")

    def test_conclusion_paragraphs_and_markdown_table_notice(self):
        reply = ("**视频人物分割推荐 SAM 3，优势是主体选择和连续跟踪。**\n\n"
                 "精细边缘仍需配合 Alpha 抠像精修。\n\n"
                 "| 对比项 | 当前方案 | SAM 3 |\n|---|---|---|\n"
                 "| 连续性 | 每帧独立推理 | 视频跟踪 |\n\n其他详细说明。")
        result = notifier.notify(self.event(**{"last-assistant-message": reply}), self.home, dry_run=True)
        self.assertEqual(result["result_summary"], "视频人物分割推荐 SAM 3，优势是主体选择和连续跟踪。\n\n精细边缘仍需配合 Alpha 抠像精修。")
        self.assertIn("回复包含对比表，详情见会话。", result["message"])
        for clutter in ("**", "|---", "每帧独立推理", "其他详细说明"):
            self.assertNotIn(clutter, result["message"])

    def test_table_without_outer_pipes_and_ordinary_pipe_text(self):
        reply = "使用 A | B 作为示例。\n\n指标 | 结果\n:--- | ---:\n成功率 | 高\n\n说明结束。"
        result = notifier.notify(self.event(**{"last-assistant-message": reply}), self.home, dry_run=True)
        self.assertEqual(result["result_summary"], "使用 A | B 作为示例。\n\n说明结束。")
        self.assertIn("回复包含对比表", result["message"])
        self.assertNotIn("成功率", result["message"])

    def test_fenced_code_is_omitted_and_prose_after_it_is_preserved(self):
        reply = "操作完成。\n\n~~~~python\nprint('<unsafe>')\n```\n~~~~\n\n- 验证通过\n- 可继续使用"
        result = notifier.notify(self.event(**{"last-assistant-message": reply}), self.home, dry_run=True)
        self.assertEqual(result["result_summary"], "操作完成。\n\n• 验证通过\n• 可继续使用")
        self.assertIn("回复包含代码，详情见会话。", result["message"])
        self.assertNotIn("print", result["message"])

    def test_only_table_or_unclosed_code_has_a_useful_notice(self):
        for reply, notice in [("| A | B |\n|---|---|\n| x | y |", "对比表"),
                              ("```python\nprint('hello')", "代码")]:
            with self.subTest(notice=notice):
                result = notifier.notify(self.event(**{"last-assistant-message": reply}), self.home, dry_run=True)
                self.assertEqual(result["result_summary"], "回复内容见会话。")
                self.assertIn("回复包含" + notice, result["message"])

    def test_two_paragraph_limit_and_sentence_boundary_truncation(self):
        result = notifier.notify(self.event(**{"last-assistant-message": "第一段。\n\n第二段。\n\n第三段。"}), self.home, dry_run=True)
        self.assertEqual(result["result_summary"], "第一段。\n\n第二段。")
        self.assertIn("更多内容见会话。", result["message"])
        reply = "结论" * 100 + "。" + "详细内容" * 100
        result = notifier.notify(self.event(**{"last-assistant-message": reply}), self.home, dry_run=True)
        self.assertEqual(result["result_summary"], "结论" * 100 + "。…")

    def test_html_entities_and_unicode_are_safe_after_truncation(self):
        result = notifier.notify(self.event(**{"thread-name": "😀<&>" * 1000,
                                               "input-messages": ["😀<&>" * 1000],
                                               "last-assistant-message": "**" + "😀<&>" * 1000 + "**"}), self.home, dry_run=True)
        tree = ElementTree.fromstring("<root>" + result["message"] + "</root>")
        visible = "".join(tree.itertext())
        self.assertLessEqual(len(visible.encode("utf-16-le")) // 2, 4096)
        self.assertNotIn("**", visible)
        self.assertNotIn("<br", result["message"])

    def test_dry_run_never_sends_or_forwards(self):
        with mock.patch.object(notifier, "send_telegram") as send, mock.patch.object(notifier, "forward_original") as forward:
            result = notifier.notify(self.event(), self.home, dry_run=True)
        self.assertTrue(result["success"])
        send.assert_not_called()
        forward.assert_not_called()

    def test_unsupported_event_and_malformed_json(self):
        with mock.patch.object(notifier, "send_telegram") as send:
            skipped = notifier.notify('{"type":"approval-requested"}', self.home, skip_original=True)
            self.assertEqual(skipped["status"], "skipped")
            for bad in ("{", "[]", "null", "{}"):
                self.assertEqual(notifier.notify(bad, self.home)["status"], "invalid-event")
            send.assert_not_called()

    def test_utf8_http_request_and_response(self):
        self.save_credentials()
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"ok":true}'
        with mock.patch.object(notifier.urllib.request, "urlopen", return_value=response) as opener:
            result = notifier.notify(self.event(), self.home, skip_original=True)
        self.assertEqual(result["status"], "sent")
        request = opener.call_args.args[0]
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["chat_id"], CHAT)
        self.assertIn("<b>Task</b>\n测试任务", body["text"])
        self.assertEqual(body["parse_mode"], "HTML")
        self.assertEqual(opener.call_args.kwargs["timeout"], 15)

    def test_http_failure_does_not_log_secret_or_url(self):
        self.save_credentials()
        with mock.patch.object(notifier.urllib.request, "urlopen", side_effect=urllib.error.URLError(TOKEN)):
            result = notifier.notify(self.event(), self.home, skip_original=True)
        self.assertEqual(result["status"], "telegram-request-failed")
        log = (notifier.managed_dir(self.home) / "error.log").read_text()
        self.assertNotIn(TOKEN, log)
        self.assertNotIn("api.telegram.org", log)

    def test_rejected_reply_is_not_reported_as_sent(self):
        self.save_credentials()
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"ok":false}'
        with mock.patch.object(notifier.urllib.request, "urlopen", return_value=response):
            self.assertEqual(notifier.notify(self.event(), self.home, skip_original=True)["status"], "telegram-rejected-message")

    def test_environment_overrides_saved_credentials(self):
        self.save_credentials()
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "654321:" + "b" * 30, "TELEGRAM_CHAT_ID": "999"}):
            self.assertEqual(notifier.credential_values(self.home), ("654321:" + "b" * 30, "999"))

    def test_windows_registry_credentials_remain_supported(self):
        with mock.patch.object(notifier, "windows_setting", side_effect=lambda key: TOKEN if key.endswith("TOKEN") else CHAT):
            self.assertEqual(notifier.credential_values(self.home), (TOKEN, CHAT))

    def test_missing_and_malformed_credentials(self):
        self.assertEqual(notifier.notify(self.event(), self.home, skip_original=True)["status"], "missing-telegram-settings")
        target = notifier.managed_dir(self.home) / "settings.json"
        target.write_text("{bad", encoding="utf-8")
        self.assertEqual(notifier.notify(self.event(), self.home, skip_original=True)["status"], "invalid-settings-file")

    def original_callback(self):
        executable = self.home / "original callback"
        executable.write_text("stub", encoding="utf-8")
        notifier.write_json(notifier.managed_dir(self.home) / "codex-original-notify.json", [str(executable), "turn-ended"])
        return executable

    def test_original_callback_argv_and_platform_process_flags(self):
        executable = self.original_callback()
        event = self.event(**{"input-messages": ['中文 "quotes" and spaces']})
        for windows in (True, False):
            with self.subTest(windows=windows), mock.patch.object(notifier, "IS_WINDOWS", windows), mock.patch.object(notifier.subprocess, "Popen") as launch:
                notifier.forward_original(self.home, event)
                self.assertEqual(launch.call_args.args[0], [str(executable), "turn-ended", event])
                self.assertNotIn("shell", launch.call_args.kwargs)
                if windows:
                    self.assertEqual(launch.call_args.kwargs["creationflags"], 0x08000000)
                else:
                    self.assertTrue(launch.call_args.kwargs["start_new_session"])

    def test_broken_original_callback_does_not_block_telegram(self):
        notifier.write_json(notifier.managed_dir(self.home) / "codex-original-notify.json", ["/does/not/exist"])
        with mock.patch.object(notifier, "send_telegram") as send:
            self.assertEqual(notifier.notify(self.event(), self.home)["status"], "sent")
            send.assert_called_once()

    def test_toml_multiline_array_preserves_other_settings(self):
        source = '# Keep this comment\r\nmodel = "example"\r\nnotify = [\r\n "old", # old callback\r\n "argument",\r\n]\r\n[features]\r\nhooks = true\r\n'
        updated = notifier.replace_notify(source, [r"C:\Program Files\Python\pythonw.exe", "/path with spaces/notify.py"])
        parsed = tomllib.loads(updated)
        self.assertEqual(parsed["model"], "example")
        self.assertTrue(parsed["features"]["hooks"])
        self.assertTrue(updated.startswith('# Keep this comment\r\nmodel = "example"\r\n'))
        self.assertIn("\r\n[features]\r\nhooks = true\r\n", updated)

    def test_toml_key_inside_multiline_string_is_not_modified(self):
        source = 'instructions = """\nnotify = ["leave me"]\n"""\n"notify" = ["real"]\n[project]\nnotify = ["nested"]\n'
        updated = notifier.replace_notify(source, ["new"])
        parsed = tomllib.loads(updated)
        self.assertIn('notify = ["leave me"]', parsed["instructions"])
        self.assertEqual(parsed["notify"], ["new"])
        self.assertEqual(parsed["project"]["notify"], ["nested"])

    def test_install_backup_repeat_install_and_original_callback(self):
        config = self.home / "config.toml"
        original = '# personal settings\nnotify = ["old", "arg"]\n[features]\nhooks = true\n'
        config.write_text(original, encoding="utf-8")
        first = notifier.install(self.home)
        self.assertEqual(Path(first["backup"]).read_text(), original)
        self.assertEqual(json.loads((notifier.managed_dir(self.home) / "codex-original-notify.json").read_text()), ["old", "arg"])
        installed = Path(first["script"])
        self.assertEqual(installed.read_bytes(), notifier.SOURCE.read_bytes())
        notifier.install(self.home)
        self.assertEqual(json.loads((notifier.managed_dir(self.home) / "codex-original-notify.json").read_text()), ["old", "arg"])
        self.assertTrue(tomllib.loads(config.read_text())["features"]["hooks"])

    def test_install_old_powershell_callback_does_not_duplicate_telegram(self):
        legacy = self.home / "legacy" / "codex-telegram.ps1"
        legacy.parent.mkdir()
        legacy.write_text("old wrapper", encoding="utf-8")
        notifier.write_json(legacy.parent / "codex-original-notify.json", ["native-callback", "turn-ended"])
        (self.home / "config.toml").write_text("notify = " + json.dumps(["powershell.exe", "-File", str(legacy)]), encoding="utf-8")
        notifier.install(self.home)
        saved = json.loads((notifier.managed_dir(self.home) / "codex-original-notify.json").read_text())
        self.assertEqual(saved, ["native-callback", "turn-ended"])

    def test_desktop_wrapped_legacy_callback_is_unlinked_to_prevent_recursion(self):
        legacy = self.home / "legacy" / "codex-telegram.ps1"
        legacy.parent.mkdir()
        legacy.write_text("legacy wrapper")
        notifier.write_json(legacy.parent / "codex-original-notify.json", ["old-native", "turn-ended"])
        wrapper = ["codex-computer-use.exe", "turn-ended", "--previous-notify",
                   json.dumps(["powershell.exe", "-File", str(legacy)])]
        (self.home / "config.toml").write_text("notify = " + json.dumps(wrapper), encoding="utf-8")
        notifier.install(self.home)
        saved = json.loads((notifier.managed_dir(self.home) / "codex-original-notify.json").read_text())
        self.assertEqual(saved, ["codex-computer-use.exe", "turn-ended"])

    def test_desktop_wrapper_preserves_unrelated_previous_callback(self):
        previous = ["other-notifier", "arg"]
        wrapper = ["codex-computer-use", "turn-ended", "--previous-notify", json.dumps(previous)]
        self.assertEqual(notifier.sanitize_original(wrapper, self.home), wrapper)

    def test_desktop_wrapped_python_callback_is_not_saved_as_a_cycle(self):
        own = [sys.executable, str(notifier.managed_dir(self.home) / "codex_telegram.py"), "notify"]
        wrapper = ["codex-computer-use.exe", "turn-ended", "--previous-notify", json.dumps(own)]
        self.assertEqual(notifier.sanitize_original(wrapper, self.home), ["codex-computer-use.exe", "turn-ended"])
        notifier.write_json(notifier.managed_dir(self.home) / "codex-original-notify.json", wrapper)
        with mock.patch.object(notifier.subprocess, "Popen") as launch:
            notifier.forward_original(self.home, self.event())
        launch.assert_not_called()

    def test_windows_install_uses_pythonw_to_avoid_console_window(self):
        executable = self.home / "python.exe"
        hidden = self.home / "pythonw.exe"
        executable.write_bytes(b"stub")
        hidden.write_bytes(b"stub")
        with mock.patch.object(notifier, "IS_WINDOWS", True), mock.patch.object(notifier.sys, "executable", str(executable)):
            result = notifier.install(self.home)
        self.assertEqual(result["notify"][0], str(hidden))

    def test_invalid_config_is_never_overwritten(self):
        config = self.home / "config.toml"
        original = b'notify = ["unclosed"'
        config.write_bytes(original)
        with self.assertRaises(ValueError):
            notifier.install(self.home)
        self.assertEqual(config.read_bytes(), original)

    def test_private_credentials_on_posix(self):
        self.save_credentials()
        if not notifier.IS_WINDOWS:
            self.assertEqual((notifier.managed_dir(self.home) / "settings.json").stat().st_mode & 0o777, 0o600)

    def test_interactive_configuration_saves_and_tests_entered_values(self):
        with mock.patch.object(sys.stdin, "isatty", return_value=True), mock.patch.object(notifier.getpass, "getpass", return_value=TOKEN), mock.patch("builtins.input", return_value=CHAT), mock.patch.object(notifier, "notify", return_value={"success": True, "status": "sent"}):
            result = notifier.configure(self.home, send_test=True)
        self.assertTrue(result["success"])
        self.assertEqual(json.loads(Path(result["settings"]).read_text())["bot_token"], TOKEN)

    def test_native_cli_json_argument_and_utf8_stdin(self):
        self.index([{"id": "session-1", "thread_name": "原生回调测试"}])
        common = [sys.executable, str(notifier.SOURCE), "--codex-home", str(self.home), "notify", "--dry-run", "--json"]
        event = self.event(**{"input-messages": ['中文 "quoted" 😀']})
        argument_run = subprocess.run([*common, event], capture_output=True, check=True)
        stdin_run = subprocess.run([*common, "--stdin"], input=event.encode("utf-8"), capture_output=True, check=True)
        for run in (argument_run, stdin_run):
            result = json.loads(run.stdout)
            self.assertEqual(result["session_name"], "原生回调测试")
            self.assertEqual(result["task_summary"], '中文 "quoted" 😀')

    def test_native_cli_failure_returns_zero_and_no_output(self):
        run = subprocess.run([sys.executable, str(notifier.SOURCE), "--codex-home", str(self.home), "notify", "{bad"], capture_output=True)
        self.assertEqual(run.returncode, 0)
        self.assertEqual(run.stdout, b"")
        self.assertEqual(run.stderr, b"")


if __name__ == "__main__":
    unittest.main()
