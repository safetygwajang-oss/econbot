"""자동 실행 인증 실패 시 입력 없이 종료하고 연결을 정리하는지 검증한다."""
from contextlib import redirect_stdout
from datetime import datetime
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import generate_telegram_session
import main as pipeline
import telegram_collector as collector
from config import KST


ENV = {"TELEGRAM_API_ID": "12345", "TELEGRAM_API_HASH": "test-api-hash", "TELEGRAM_SESSION": "test-session"}


class TelegramAuthTests(unittest.TestCase):
    def collect_with(self, client):
        with patch.dict(os.environ, ENV), \
             patch.object(collector, "_load_session", return_value=Mock()), \
             patch.object(collector, "TelegramClient", return_value=client), \
             patch("builtins.input", side_effect=AssertionError("자동 실행에서 입력을 요청함")):
            return collector.fetch_messages()

    def test_unauthorized_session_never_prompts_and_disconnects(self):
        client = Mock()
        client.is_user_authorized.return_value = False
        with self.assertRaisesRegex(collector.TelegramSessionError, "TELEGRAM_SESSION"):
            self.collect_with(client)
        client.connect.assert_called_once()
        client.disconnect.assert_called_once()
        client.start.assert_not_called()
        client.get_dialogs.assert_not_called()

    def test_authorized_user_prepares_channels_and_collects_messages(self):
        client = Mock()
        client.is_user_authorized.return_value = True
        client.is_bot.return_value = False
        client.get_entity.return_value = Mock(title="자료 채널")
        message = Mock()
        message.date = datetime(2026, 10, 2, 12, 0, tzinfo=KST)
        message.message = "테스트 경제 자료입니다."
        message.id = 7
        client.iter_messages.return_value = [message]
        with patch.object(collector, "TARGET_CHATS", [-100123]), \
             patch.object(collector, "Message", Mock), \
             patch.object(collector, "_get_time_range", return_value=(
                 datetime(2026, 10, 2, 8, tzinfo=KST),
                 datetime(2026, 10, 3, 8, tzinfo=KST),
             )):
            messages = self.collect_with(client)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["text"], message.message)
        calls = [call[0] for call in client.method_calls]
        self.assertLess(calls.index("get_dialogs"), calls.index("get_entity"))
        client.start.assert_not_called()
        client.disconnect.assert_called_once()

    def test_bot_session_is_rejected_before_channel_reads(self):
        client = Mock()
        client.is_user_authorized.return_value = True
        client.is_bot.return_value = True
        with self.assertRaisesRegex(collector.TelegramSessionError, "개인 계정"):
            self.collect_with(client)
        client.get_dialogs.assert_not_called()
        client.disconnect.assert_called_once()

    def test_network_failure_still_disconnects(self):
        client = Mock()
        client.connect.side_effect = ConnectionError("연결 실패")
        with self.assertRaises(ConnectionError):
            self.collect_with(client)
        client.disconnect.assert_called_once()

    def test_authentication_revoked_during_channel_lookup_is_not_hidden(self):
        client = Mock()
        client.is_user_authorized.return_value = True
        client.is_bot.return_value = False
        client.get_entity.side_effect = collector.UnauthorizedError(
            request=None, message="AUTH_KEY_UNREGISTERED"
        )
        with self.assertRaisesRegex(collector.TelegramSessionError, "인증"):
            self.collect_with(client)
        client.disconnect.assert_called_once()

    def test_pipeline_auth_failure_stops_before_cafe_posting(self):
        output = io.StringIO()
        with patch.object(pipeline, "fetch_messages", side_effect=collector.TelegramSessionError("세션 재발급 필요")), \
             patch.object(pipeline, "get_access_token") as token, \
             patch.object(pipeline, "post_all_unified") as post, \
             redirect_stdout(output):
            self.assertEqual(pipeline.main(), 1)
        token.assert_not_called()
        post.assert_not_called()
        self.assertIn("세션 재발급 필요", output.getvalue())

    def test_all_inaccessible_channels_raise_clear_error(self):
        client = Mock()
        client.is_user_authorized.return_value = True
        client.is_bot.return_value = False
        client.get_entity.side_effect = ValueError("채널 정보를 찾을 수 없음")
        with self.assertRaisesRegex(RuntimeError, "채널 참여 여부"):
            self.collect_with(client)
        client.disconnect.assert_called_once()

    def test_blank_session_fails_without_creating_client(self):
        with patch.dict(os.environ, {"TELEGRAM_SESSION": "   "}), \
             patch.object(collector, "StringSession") as session:
            with self.assertRaisesRegex(collector.TelegramSessionError, "비어"):
                collector._load_session()
        session.assert_not_called()

    def test_session_parser_errors_do_not_expose_the_session(self):
        secret = "bad-private-session"
        with patch.dict(os.environ, {"TELEGRAM_SESSION": secret}), \
             patch.object(collector, "StringSession", side_effect=ValueError(secret)):
            with self.assertRaises(collector.TelegramSessionError) as caught:
                collector._load_session()
        self.assertNotIn(secret, str(caught.exception))

    def test_copied_session_quotes_and_whitespace_are_cleaned(self):
        with patch.dict(os.environ, {"TELEGRAM_SESSION": '  "test-session"\n'}), \
             patch.object(collector, "StringSession", return_value=Mock(auth_key=True)) as session:
            collector._load_session()
        session.assert_called_once_with("test-session")

    def test_generator_refuses_github_actions_without_prompting(self):
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}), \
             patch("sys.argv", ["generate_telegram_session.py"]), \
             patch("builtins.input", side_effect=AssertionError("입력 요청")), \
             patch.object(generate_telegram_session, "TelegramClient") as client, \
             redirect_stdout(io.StringIO()):
            self.assertEqual(generate_telegram_session.main(), 1)
        client.assert_not_called()

    def test_generator_saves_session_without_printing_it(self):
        client = Mock()
        client.is_bot.return_value = False
        client.session.save.return_value = "private-session-value"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "session.txt"
            logs = io.StringIO()
            with patch.dict(os.environ, {"GITHUB_ACTIONS": "false", **ENV}), \
                 patch("sys.stdin.isatty", return_value=True), \
                 patch("sys.argv", ["generate_telegram_session.py", "--output", str(output)]), \
                 patch.object(generate_telegram_session, "TelegramClient", return_value=client), \
                 redirect_stdout(logs):
                self.assertEqual(generate_telegram_session.main(), 0)
            self.assertEqual(output.read_text(), "private-session-value")
            self.assertNotIn("private-session-value", logs.getvalue())
            if os.name == "posix":
                self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        client.disconnect.assert_called_once()


if __name__ == "__main__":
    unittest.main()
