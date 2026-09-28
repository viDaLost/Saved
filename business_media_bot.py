"""Telegram Business selective message inbox (Python 3.10+, stdlib only).

Setup:
  1. Create a bot with @BotFather, enable Business Mode in its settings.
  2. Open the bot's private chat, send /id, and copy the returned numeric ID.
  3. Set BOT_TOKEN and OWNER_ID in the environment, then run this script.
  4. Send /start to the bot and connect it under Telegram Settings >
     Telegram Business > Chatbots (choose which chats the bot can access).

Example on macOS/Linux:
  export BOT_TOKEN='token-from-BotFather'
  export OWNER_ID='123456789'
  python3 business_media_bot.py

To select a message, reply to it in the business chat (swipe right and send
any reply). The bot sends only the message you replied to, not every incoming
message. The source must be present in reply_to_message.
Telegram may omit reply_to_message for ephemeral messages. This bot does not
access view-once, expiring or protected content.
The bot does not write media or tokens to disk. Keep the token secret.
"""

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


TOKEN = os.environ.get("BOT_TOKEN", "").strip()
OWNER_ID = os.environ.get("OWNER_ID", "").strip()
if not TOKEN:
    raise SystemExit("Set BOT_TOKEN first.")
if OWNER_ID and not OWNER_ID.isdecimal():
    raise SystemExit("OWNER_ID must be a numeric Telegram user ID.")

API = f"https://api.telegram.org/bot{TOKEN}/"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
connection_cache = {}


def start_health_server():
    """Optional HTTP endpoint required by Timeweb App Platform deployment."""
    port = os.environ.get("HEALTH_PORT")
    if not port:
        return

    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in ("/", "/health"):
                self.send_error(404)
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, _format, *_args):
            pass

    server = ThreadingHTTPServer(("0.0.0.0", int(port)), HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()


def api(method, **params):
    payload = json.dumps(params).encode("utf-8")
    req = urllib.request.Request(
        API + method, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        # Do not log full URLs: they contain the secret bot token.
        raise RuntimeError(f"{method}: HTTP {exc.code}") from None
    if not result.get("ok"):
        raise RuntimeError(f"{method}: {result.get('description', 'Telegram API error')}")
    return result["result"]


def message_payload(message):
    """Return (send method, parameters) for a selected message, if supported."""
    if message.get("has_protected_content"):
        return None
    if message.get("text"):
        params = {"text": message["text"]}
        if message.get("entities"):
            params["entities"] = message["entities"]
        return "sendMessage", params
    photo = message.get("photo")
    if photo:
        media = "sendPhoto", {"photo": photo[-1]["file_id"]}
    else:
        media = None
    for key, method in (
        ("video", "sendVideo"),
        ("audio", "sendAudio"),
        ("voice", "sendVoice"),
        ("video_note", "sendVideoNote"),
        ("document", "sendDocument"),
        ("animation", "sendAnimation"),
        ("sticker", "sendSticker"),
    ):
        item = message.get(key)
        if item and item.get("file_id"):
            media = method, {key: item["file_id"]}
            break
    if media:
        method, params = media
        if method not in ("sendVideoNote", "sendSticker") and message.get("caption"):
            params["caption"] = message["caption"]
            if message.get("caption_entities"):
                params["caption_entities"] = message["caption_entities"]
        return method, params
    if message.get("venue"):
        venue = message["venue"]
        return "sendVenue", {key: venue[key] for key in ("latitude", "longitude", "title", "address")}
    if message.get("location"):
        location = message["location"]
        return "sendLocation", {key: location[key] for key in ("latitude", "longitude")}
    if message.get("contact"):
        contact = message["contact"]
        params = {key: contact[key] for key in ("phone_number", "first_name")}
        for key in ("last_name", "vcard"):
            if contact.get(key):
                params[key] = contact[key]
        return "sendContact", params
    if message.get("dice"):
        return "sendMessage", {"text": f"Бросок {message['dice']['emoji']}: {message['dice']['value']}"}
    if message.get("poll"):
        poll = message["poll"]
        options = "\n".join(f"• {option['text']}" for option in poll.get("options", []))
        return "sendMessage", {"text": f"Опрос: {poll['question']}\n{options}"}
    return None


def handle(update):
    global OWNER_ID
    direct = update.get("message")
    if direct and direct.get("chat", {}).get("type") == "private":
        sender_id = str(direct.get("from", {}).get("id", ""))
        chat_id = direct["chat"]["id"]
        if direct.get("text", "").split(maxsplit=1)[0:1] == ["/id"]:
            api("sendMessage", chat_id=chat_id, text=f"Ваш Telegram ID: {sender_id}")
        elif OWNER_ID and sender_id == OWNER_ID and direct.get("text", "").startswith("/start"):
            api("sendMessage", chat_id=chat_id, text="Бот готов. Подключите его в настройках Telegram Business. Чтобы сохранить сообщение, ответьте на него в бизнес-чате (свайпом и любым сообщением). Только выбранное сообщение придёт сюда.")

    connection = update.get("business_connection")
    if connection:
        connection_cache[connection["id"]] = connection
        if OWNER_ID and str(connection.get("user", {}).get("id")) == OWNER_ID:
            logging.info("Business connection enabled=%s", connection.get("is_enabled"))

    message = update.get("business_message")
    if not message or not OWNER_ID:
        return
    connection_id = message.get("business_connection_id")
    if not connection_id:
        return
    connection = connection_cache.get(connection_id)
    if not connection:
        connection = api("getBusinessConnection", business_connection_id=connection_id)
        connection_cache[connection_id] = connection
    if not connection.get("is_enabled") or str(connection.get("user", {}).get("id")) != OWNER_ID:
        return
    # The selection action must be a human reply sent by the account owner.
    if str(message.get("from", {}).get("id")) != OWNER_ID or message.get("sender_business_bot") or message.get("is_from_offline"):
        return
    original = message.get("reply_to_message")
    if not original or not original.get("message_id"):
        return
    if str(original.get("from", {}).get("id")) == OWNER_ID:
        return
    item = message_payload(original)
    if not item:
        return
    method, payload = item
    payload["chat_id"] = int(OWNER_ID)
    api(method, **payload)
    logging.info("Delivered selected message via %s from business chat %s", method, message["chat"]["id"])


def main():
    start_health_server()
    if not OWNER_ID:
        logging.warning("OWNER_ID missing; only /id will work until you configure it and restart.")
    offset = None
    while True:
        try:
            params = {"timeout": 25, "allowed_updates": ["message", "business_connection", "business_message"]}
            if offset is not None:
                params["offset"] = offset
            for update in api("getUpdates", **params):
                try:
                    handle(update)
                except Exception as exc:
                    logging.error("Update %s: %s", update.get("update_id"), exc)
                offset = update["update_id"] + 1
        except KeyboardInterrupt:
            break
        except Exception as exc:
            logging.error("Polling: %s", exc)
            time.sleep(5)


if __name__ == "__main__":
    main()
