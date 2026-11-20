import os
import json
import asyncio
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

TOKEN = "8802626648:AAHYegmfNfmTSQoXIYkLL3Mu3Ok-QrEZI2Q"
ADMIN_ID = 8405165103

DATA_FILE = "scammers.json"


def load_json(filename):
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


scammers_db = load_json(DATA_FILE)

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN)
dp = Dispatcher()


def get_main_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="Список мошенников", callback_data="list_scammers")
    builder.button(text="Статистика базы", callback_data="stats")
    builder.adjust(1)
    return builder.as_markup()


@dp.message(Command("start", "menu"))
async def cmd_menu(message: types.Message):
    if not message.from_user or message.from_user.id != ADMIN_ID:
        return
    await message.answer("Панель управления базой мошенников:", reply_markup=get_main_menu())


@dp.callback_query(F.data == "stats")
async def show_stats(callback: types.CallbackQuery):
    if not callback.from_user or callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return
    count = len(scammers_db)
    await callback.message.edit_text(
        f"Статистика:\nВсего записей в базе: {count}",
        reply_markup=get_main_menu()
    )
    await callback.answer()


@dp.callback_query(F.data == "list_scammers")
async def show_list(callback: types.CallbackQuery):
    if not callback.from_user or callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return

    if not scammers_db:
        text = "База мошенников пока пуста."
    else:
        text = "Список мошенников:\n\n"
        for user, info in list(scammers_db.items())[:10]:
            reason = info.get("reason", "Нет причины") if isinstance(info, dict) else str(info)
            text += f"• {user} — {reason}\n"

    builder = InlineKeyboardBuilder()
    builder.button(text="Назад в меню", callback_data="back_menu")

    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


@dp.callback_query(F.data == "back_menu")
async def back_to_menu(callback: types.CallbackQuery):
    if not callback.from_user or callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return
    await callback.message.edit_text("Панель управления базой мошенников:", reply_markup=get_main_menu())
    await callback.answer()


@dp.message(F.text & (F.text.lower().startswith("жалоба") | F.text.lower().startswith("репорт") | F.text.startswith("/add")))
async def handle_report(message: types.Message):
    if not message.from_user or message.from_user.id != ADMIN_ID:
        return

    text = message.text
    for prefix in ["/add", "жалоба", "репорт"]:
        if text.lower().startswith(prefix):
            text = text[len(prefix):].strip()
            break

    args = text.split("|")
    if len(args) < 2:
        await message.reply("Формат репорта: <username/id> | <причина> [| пруфы]")
        return

    target = args[0].strip()
    reason = args[1].strip()
    proof = args[2].strip() if len(args) > 2 else "Нет пруфов"

    scammers_db[target] = {"reason": reason, "proof": proof}
    save_json(DATA_FILE, scammers_db)
    await message.reply(f"Пользователь {target} добавлен в базу.")


@dp.message(F.document)
async def handle_db_file(message: types.Message):
    if not message.from_user or message.from_user.id != ADMIN_ID:
        return

    doc = message.document
    if not doc.file_name or not doc.file_name.endswith(".json"):
        await message.reply("Кидай файл в формате .json")
        return

    file_info = await bot.get_file(doc.file_id)
    downloaded = await bot.download_file(file_info.file_path)

    try:
        raw_text = downloaded.read().decode("utf-8")
        new_data = json.loads(raw_text)
        if not isinstance(new_data, dict):
            await message.reply("Внутри JSON должен быть объект (словарь).")
            return

        global scammers_db
        scammers_db = new_data
        save_json(DATA_FILE, scammers_db)
        await message.reply(f"База обновлена! Загружено записей: {len(scammers_db)}")
    except Exception as e:
        await message.reply(f"Ошибка при чтении файла: {e}")


@dp.message(F.text)
async def check_scammer(message: types.Message):
    if not message.text:
        return

    raw = message.text.strip()
    if raw.startswith("/") or "|" in raw:
        return

    query = raw.lower()
    found_key = None

    for key in scammers_db.keys():
        if key.lower() == query or key.lower() in query:
            found_key = key
            break

    if found_key:
        info = scammers_db[found_key]
        if isinstance(info, dict):
            reason = info.get("reason", "Не указана")
            proof = info.get("proof", "Нет пруфов")
        else:
            reason = str(info)
            proof = "Нет пруфов"
        await message.reply(
            f"Найдено совпадение в базе: {found_key}\n"
            f"Причина: {reason}\n"
            f"Пруфы: {proof}"
        )
    elif raw.startswith("@"):
        await message.reply(f"Пользователь {raw} в базе не найден.")


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
    logging.info("Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())