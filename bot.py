import asyncio
import logging
import os
import json
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, BotCommand, FSInputFile
from aiohttp import web

TOKEN = '88026648:AAHYegmfNfmTSQoXIYKLL3Mu30k-QreZI2Q'
ADMIN_ID = 8405165103
ALLOWED_GROUP_ID = 0

DATA_FILE = 'scammers.json'

def load_local_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}

scammers_db = load_local_data()

async def save_and_backup_data(bot: Bot):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(scammers_db, f, ensure_ascii=False, indent=4)
    
    try:
        file = FSInputFile(DATA_FILE)
        await bot.send_document(ADMIN_ID, document=file, caption="📁 Автоматический бэкап базы скамеров")
    except Exception as e:
        print(f"Ошибка бэкапа: {e}")

class AddScammerState(StatesGroup):
    waiting_for_reason = State()
    waiting_for_media = State()

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Привет! Я бот для проверки и ведения базы скамеров.\n\n"
        "📌 **Как я работаю:**\n"
        "• Напиши в группе юзернейм (например, `@username`) или ID, и я сразу проверю его по базе.\n"
        "• Если человек есть в базе — я выдам предупреждение.\n"
        "• Если человека нет в базе — я напишу, что он чист.\n\n"
        "👑 **Команды для админа:**\n"
        "• `/add @username Причина` — добавить скамера\n"
        "• `/del @username` — удалить из базы"
    )

@dp.message(Command("add"))
async def cmd_add(message: types.Message, command: CommandObject, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    
    if not command.args:
        await message.answer("❌ Использование: `/add @username Причина` или `/add ID Причина`")
        return
    
    args = command.args.split(maxsplit=1)
    target = args[0].strip()
    reason = args[1].strip() if len(args) > 1 else "Причина не указана"
    
    await state.update_data(target=target, reason=reason, media=[])
    await message.answer(f"📝 Цель: `{target}`\nПричина: {reason}\n\n📸 Теперь отправь скриншоты или голосовые (доказательства). Когда закончишь, отправь команду `/done`.")
    await state.set_state(AddScammerState.waiting_for_media)

@dp.message(AddScammerState.waiting_for_media, F.photo)
async def process_media_photo(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    data = await state.get_data()
    media_list = data.get("media", [])
    photo = message.photo[-1].file_id
    media_list.append({"type": "photo", "file_id": photo})
    await state.update_data(media=media_list)
    await message.answer(f"✅ Фото добавлено ({len(media_list)} шт.). Отправь еще или напиши `/done`.")

@dp.message(AddScammerState.waiting_for_media, F.voice)
async def process_media_voice(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    data = await state.get_data()
    media_list = data.get("media", [])
    voice = message.voice.file_id
    media_list.append({"type": "voice", "file_id": voice})
    await state.update_data(media=media_list)
    await message.answer(f"✅ Голосовое добавлено. Отправь еще файлы или напиши `/done`.")

@dp.message(AddScammerState.waiting_for_media, Command("done"))
async def process_done(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    data = await state.get_data()
    target = data.get("target")
    reason = data.get("reason")
    media = data.get("media", [])
    
    scammers_db[target] = {
        "reason": reason,
        "media": media
    }
    await save_and_backup_data(message.bot)
    await state.clear()
    await message.answer(f"🎉 Пользователь `{target}` успешно добавлен в базу скамеров!")

@dp.message(Command("del"))
async def cmd_del(message: types.Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        return
    if not command.args:
        await message.answer("❌ Укажи юзернейм или ID для удаления: `/del @username`")
        return
    
    target = command.args.strip()
    if target in scammers_db:
        del scammers_db[target]
        await save_and_backup_data(message.bot)
        await message.answer(f"🗑 Пользователь `{target}` удален из базы.")
    else:
        await message.answer(f"❌ Пользователь `{target}` не найден в базе.")

@dp.message(F.chat.type.in_({'group', 'supergroup'}))
async def check_in_group(message: types.Message, bot: Bot):
    if ALLOWED_GROUP_ID != 0 and message.chat.id != ALLOWED_GROUP_ID:
        return
    
    text = message.text or message.caption or ""
    if not text:
        return

    words = text.split()
    found_target = None
    
    for word in words:
        clean_word = word.strip(",.!?;:()[]{}*\"'")
        if clean_word.startswith("@") or clean_word.isdigit():
            if clean_word in scammers_db:
                found_target = clean_word
                break

    if found_target:
        data = scammers_db[found_target]
        reason = data.get("reason", "Причина не указана")
        media = data.get("media", [])
        
        warning_text = (
            f"⚠️ **ВНИМАНИЕ! ЭТО СКАМЕР!**\n\n"
            f"🎯 **Нарушитель:** {found_target}\n"
            f"❌ **Статус:** НАЙДЕН В БАЗЕ СКАМА\n"
            f"📝 **Причина:** {reason}"
        )
        
        if media:
            first_item = media[0]
            if first_item["type"] == "photo":
                media_group = [InputMediaPhoto(media=first_item["file_id"], caption=warning_text, parse_mode="Markdown")]
                for m in media[1:]:
                    if m["type"] == "photo":
                        media_group.append(InputMediaPhoto(media=m["file_id"]))
                await message.reply_album(media=media_group)
            elif first_item["type"] == "voice":
                await message.reply(warning_text, parse_mode="Markdown")
                await message.reply_voice(voice=first_item["file_id"])
        else:
            await message.reply(warning_text, parse_mode="Markdown")
    else:
        for word in words:
            clean_word = word.strip(",.!?;:()[]{}*\"'")
            if clean_word.startswith("@"):
                await message.reply(f"🔍 Проверил `{clean_word}`: в базе скамеров **не найден** (чист).", parse_mode="Markdown")
                break

async def handle(request):
    return web.Response(text="Bot is running!")

async def web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_my_commands([
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="add", description="Добавить скамера (админ)"),
        BotCommand(command="del", description="Удалить скамера (админ)")
    ])
    asyncio.create_task(web_server())
    print("Бот успешно запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())