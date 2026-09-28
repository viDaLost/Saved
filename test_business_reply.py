"""Regression tests for replies whose original media Telegram omits."""

import importlib
import os
import unittest
from unittest.mock import patch


class ReplyTests(unittest.TestCase):
    def setUp(self):
        with patch.dict(os.environ, {"BOT_TOKEN": "test", "OWNER_ID": "123"}):
            import business_media_bot
            self.bot = importlib.reload(business_media_bot)
        self.bot.connection_cache["connection"] = {
            "is_enabled": True, "user": {"id": 123}
        }
        self.sent = []

        def fake_api(method, **kwargs):
            self.sent.append((method, kwargs))
            if method == "copyMessage" and self.copy_fails:
                raise RuntimeError("copyMessage: HTTP 400")
            return True

        self.copy_fails = False
        self.api_patch = patch.object(self.bot, "api", side_effect=fake_api)
        self.api_patch.start()
        self.addCleanup(self.api_patch.stop)

    def outgoing(self, **additional):
        message = {
            "business_connection_id": "connection",
            "chat": {"id": 456},
            "from": {"id": 123},
            "text": "ответ",
        }
        message.update(additional)
        return {"business_message": message}

    def test_missing_original_does_not_send_unselected_content(self):
        self.bot.handle(self.outgoing(text="секретный текст"))
        self.assertEqual(self.sent, [])
        self.assertIn("не передал ID", self.bot.debug_text())
        self.assertNotIn("секретный текст", self.bot.debug_text())

    def test_original_photo_is_sent_by_file_id(self):
        self.bot.handle(self.outgoing(reply_to_message={
            "message_id": 7, "photo": [{"file_id": "a"}], "from": {"id": 789}
        }))
        self.assertEqual(self.sent[0], ("sendPhoto", {"photo": "a", "chat_id": 123}))

    def test_reply_id_without_media_tries_copy_then_falls_back(self):
        self.copy_fails = True
        self.bot.handle(self.outgoing(reply_to_message={"message_id": 7, "from": {"id": 789}}))
        self.assertEqual(self.sent[0], ("copyMessage", {
            "chat_id": 123, "from_chat_id": 456, "message_id": 7
        }))
        self.assertEqual(self.sent[1][0], "sendMessage")

    def test_external_reply_must_be_same_chat(self):
        self.bot.handle(self.outgoing(external_reply={"chat": {"id": 999}, "message_id": 7}))
        self.assertEqual(self.sent, [])

    def test_debug_is_owner_only(self):
        self.bot.handle({"message": {"chat": {"id": 9, "type": "private"},
                                     "from": {"id": 9}, "text": "/debug"}})
        self.assertEqual(self.sent, [])


if __name__ == "__main__":
    unittest.main()
