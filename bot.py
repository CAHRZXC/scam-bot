import asyncio
import json
import logging
import os
import sys
from aiohttp import web
from telethon import Button, TelegramClient, events
from telethon.sessions import StringSession

API_ID = 39070752
API_HASH = "a7f4346ee8e737e2c176d557a1e8df32"
ADMIN_ID = 8405165103

DATA_FILE = "scammers.json"
GROUPS_FILE = "allowed_groups.json"


def load_json(filename):
  if os.path.exists(filename):
    try:
      with open(filename, "r", encoding="utf-8") as f:
        return json.load(f)
    except Exception:
      return {}
  return {}


def save_json(filename, data):
  with open(filename, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=4)


scammers_db = load_json(DATA_FILE)
allowed_groups = load_json(GROUPS_FILE)

logging.basicConfig(level=logging.INFO)
session_string = os.environ.get("SESSION_STRING")
client = TelegramClient(StringSession(session_string), API_ID, API_HASH)


@client.on(events.NewMessage(pattern=r"^/add (.+)"))
async def add_scammer(event):
  if event.sender_id != ADMIN_ID:
    return
  args = event.pattern_match.group(1).split("|")
  if len(args) < 2:
    await event.respond(
        "Использование: /add <username/id> | <причина> [| пруфы]"
    )
    return

  target = args[0].strip()
  reason = args[1].strip()
  proof = args[2].strip() if len(args) > 2 else "Нет пруфов"

  scammers_db[target] = {"reason": reason, "proof": proof}
  save_json(DATA_FILE, scammers_db)
  await event.respond(f"Успешно добавлено в базу: {target}")


@client.on(events.NewMessage(pattern=r"^/del (.+)"))
async def del_scammer(event):
  if event.sender_id != ADMIN_ID:
    return
  target = event.pattern_match.group(1).strip()
  if target in scammers_db:
    del scammers_db[target]
    save_json(DATA_FILE, scammers_db)
    await event.respond(f"Успешно удалено: {target}")
  else:
    await event.respond("Не найдено в базе.")


@client.on(events.NewMessage(pattern=r"^/check (.+)"))
async def check_scammer(event):
  target = event.pattern_match.group(1).strip()
  if target in scammers_db:
    info = scammers_db[target]
    await event.respond(
        f"⚠️ ВНИМАНИЕ! Обнаружен в базе скамеров!\nЦель: {target}\nПричина:"
        f" {info['reason']}\nПруфы: {info['proof']}"
    )
  else:
    await event.respond(f"✅ Пользователь {target} не найден в базе скамеров.")


@client.on(events.NewMessage())
async def monitor_chats(event):
  if not event.is_group and not event.is_channel:
    return

  chat_id = str(event.chat_id)
  sender = await event.get_sender()
  if not sender:
    return

  user_identifiers = [str(sender.id)]
  if sender.username:
    user_identifiers.append(f"@{sender.username.lower()}")

  for uid in user_identifiers:
    if uid in scammers_db:
      info = scammers_db[uid]
      warning_text = (
          f"🚨 Автоматическое предупреждение!\nОбнаружен участник из базы"
          f" скамеров:\nЦель: {uid}\nПричина: {info['reason']}\nПруфы:"
          f" {info['proof']}"
      )
      try:
        await event.reply(warning_text)
      except Exception:
        pass
      break


async def handle_ping(request):
  return web.Response(text="Bot is running!")


async def start_web_server():
  app = web.Application()
  app.router.add_get("/", handle_ping)
  runner = web.AppRunner(app)
  await runner.setup()
  port = int(os.environ.get("PORT", 8080))
  site = web.TCPSite(runner, "0.0.0.0", port)
  await site.start()


async def main():
  await start_web_server()
  print("Бот успешно запущен и работает!")
  await client.run_until_disconnected()


if __name__ == "__main__":
  with client:
    client.loop.run_until_complete(main())
