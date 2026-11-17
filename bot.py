import os
import json
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
                return json.load(f)
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
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("Панель управления базой мошенников:", reply_markup=get_main_menu())

@dp.callback_query(F.data == "stats")
async def show_stats(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    count = len(scammers_db)
    await callback.message.edit_text(
        f"Статистика:\nВсего записей в базе: {count}",
        reply_markup=get_main_menu()
    )
    await callback.answer()

@dp.callback_query(F.data == "list_scammers")
async def show_list(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    
    if not scammers_db:
        text = "База мошенников пока пуста."
    else:
        text = "Список мошенников:\n\n"
        for user, info in list(scammers_db.items())[:10]:
            text += f"• {user} — {info.get('reason', 'Нет причины')}\n"
            
    builder = InlineKeyboardBuilder()
    builder.button(text="Назад в меню", callback_data="back_menu")
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "back_menu")
async def back_to_menu(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.message.edit_text("Панель управления базой мошенников:", reply_markup=get_main_menu())
    await callback.answer()

# Обработка репортов (если реплика содержит жалобу или оформлена как репорт)
@dp.message(F.text & (F.text.lower().startswith("жалоба") | F.text.lower().startswith("репорт") | F.text.startswith("/add")))
async def handle_report(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    text = message.text
    for prefix in ["/add", "жалоба", "репорт"]:
        if text.lower().startswith(prefix):
            text = text[len(prefix):].strip()
            break
            
    args = text.split("|")
    if len(args) < 2:
        await message.answer("Использование формата репорта: <username/id> | <причина>")
        return
    
    target = args[0].strip()
    reason = args[1].strip()
    proof = args[2].strip() if len(args) > 2 else "Нет пруфов"
    
    scammers_db[target] = {"reason": reason, "proof": proof}
    save_json(DATA_FILE, scammers_db)
    await message.answer(f"Пользователь {target} успешно добавлен по репорту!")

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
    print("Бот запущен и ждет репорты!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())