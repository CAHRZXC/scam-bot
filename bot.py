import os
import re
import json
import asyncio
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

TOKEN = "8802626648:AAHYegmfNfmTSQoXIYkLL3Mu3Ok-QrEZI2Q"
ADMIN_ID = 8405165103
REPORTS_CHANNEL_ID = -1003725925366

DATA_FILE = "scammers.json"
PENDING_FILE = "pending_reports.json"


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
pending_reports = load_json(PENDING_FILE)

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())


class ReportForm(StatesGroup):
    waiting_target = State()
    waiting_details = State()


def get_reply_menu():
    builder = ReplyKeyboardBuilder()
    builder.button(text="Подать жалобу")
    builder.button(text="Проверить юзер")
    builder.button(text="Статистика")
    builder.button(text="Что за бот")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)


def get_admin_inline_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="Список базы", callback_data="list_scammers")
    builder.button(text="Статистика", callback_data="stats")
    builder.adjust(1)
    return builder.as_markup()


def get_moderation_keyboard(report_id: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="Подтвердить жалобу", callback_data=f"approve_rep:{report_id}")
    builder.button(text="Отклонить", callback_data=f"reject_rep:{report_id}")
    builder.adjust(2)
    return builder.as_markup()


def extract_target(text: str):
    if not text:
        return None
    username_match = re.search(r"@[A-Za-z0-9_]{3,}", text)
    if username_match:
        return username_match.group(0)
    id_match = re.search(r"\b\d{5,15}\b", text)
    if id_match:
        return id_match.group(0)
    return None


def resolve_display_id(target: str, message: types.Message, db_entry):
    if isinstance(db_entry, dict) and db_entry.get("id"):
        return f"`{db_entry['id']}`"
    if target.isdigit():
        return f"`{target}`"
    if message.reply_to_message and message.reply_to_message.from_user:
        rep_user = message.reply_to_message.from_user
        if rep_user.username and f"@{rep_user.username.lower()}" == target.lower():
            return f"`{rep_user.id}`"
    return "`Скрыт (еще не писал в группе)`"


@dp.message(Command("start", "menu"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    if message.chat.type == "private":
        await message.answer(
            "Бот проверки пользователей и приёма жалоб.\n"
            "В группах просто отправь @username или ID — я проверю по базе.",
            reply_markup=get_reply_menu()
        )
    if message.from_user and message.from_user.id == ADMIN_ID:
        await message.answer("Панель администратора:", reply_markup=get_admin_inline_menu())


@dp.message(F.text == "Что за бот")
async def btn_about(message: types.Message):
    await message.answer(
        "Бот проверяет пользователей и ID по базе скамеров.\n"
        "Чтобы подать жалобу — нажми «Подать жалобу» или напиши /report.",
        reply_markup=get_reply_menu() if message.chat.type == "private" else None
    )


@dp.message(F.text == "Статистика")
async def btn_stats(message: types.Message):
    await message.answer(f"Записей в базе: {len(scammers_db)}")


@dp.message(F.text == "Проверить юзер")
async def btn_check_prompt(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Отправь @username или ID пользователя для проверки.")


@dp.message(F.text == "Подать жалобу")
@dp.message(Command("report"))
async def start_user_report(message: types.Message, state: FSMContext):
    await state.clear()
    await state.set_state(ReportForm.waiting_target)
    await message.answer("Введите логин (@username) или ID мошенника:")


@dp.message(ReportForm.waiting_target, F.text)
async def process_report_target(message: types.Message, state: FSMContext):
    target = message.text.strip()
    if not target:
        await message.answer("Введите логин или ID мошенника:")
        return
    await state.update_data(report_target=target)
    await state.set_state(ReportForm.waiting_details)
    await message.answer(
        "Опишите ситуацию и отправьте скрины/ссылки одним сообщением:\n\n"
        "❗️ Пожалуйста, убедитесь, что все личные данные зарисованы, прежде чем отправлять. "
        "В противном случае жалоба будет отклонена.\n\n"
        "❗️ Отправьте не более 10 скриншотов одним сообщением."
    )


@dp.message(ReportForm.waiting_details)
async def process_report_details(message: types.Message, state: FSMContext):
    media_type = None
    file_id = None

    if message.photo:
        media_type = "photo"
        file_id = message.photo[-1].file_id
    elif message.video:
        media_type = "video"
        file_id = message.video.file_id
    elif message.voice:
        media_type = "voice"
        file_id = message.voice.file_id
    elif message.video_note:
        media_type = "video_note"
        file_id = message.video_note.file_id
    elif message.document:
        media_type = "document"
        file_id = message.document.file_id

    if not media_type:
        await message.answer("Жалобы без пруфов не принимаются")
        return

    data = await state.get_data()
    target = data.get("report_target", "Не указан")
    sender = message.from_user
    sender_id = sender.id if sender else 0
    sender_info = f"@{sender.username}" if sender and sender.username else f"ID {sender_id}"
    description = message.caption or message.text or "(без текстового описания)"

    report_id = str(message.message_id) + f"_{sender_id}"

    pending_reports[report_id] = {
        "target": target,
        "sender_info": sender_info,
        "sender_id": sender_id,
        "description": description,
        "media_type": media_type,
        "file_id": file_id,
    }
    save_json(PENDING_FILE, pending_reports)

    admin_text = (
        "🚨 **НОВАЯ ЖАЛОБА НА ПРОВЕРКУ**\n\n"
        f"👤 **Нарушитель:** {target}\n"
        f"📨 **Отправитель:** {sender_info} (`{sender_id}`)\n"
        f"📝 **Описание:** {description}"
    )

    try:
        if media_type == "photo" and file_id:
            await bot.send_photo(
                chat_id=ADMIN_ID,
                photo=file_id,
                caption=admin_text,
                parse_mode="Markdown",
                reply_markup=get_moderation_keyboard(report_id)
            )
        elif media_type == "video" and file_id:
            await bot.send_video(
                chat_id=ADMIN_ID,
                video=file_id,
                caption=admin_text,
                parse_mode="Markdown",
                reply_markup=get_moderation_keyboard(report_id)
            )
        elif media_type == "voice" and file_id:
            await bot.send_voice(
                chat_id=ADMIN_ID,
                voice=file_id,
                caption=admin_text,
                parse_mode="Markdown",
                reply_markup=get_moderation_keyboard(report_id)
            )
        elif media_type == "video_note" and file_id:
            await bot.send_video_note(
                chat_id=ADMIN_ID,
                video_note=file_id
            )
            await bot.send_message(
                chat_id=ADMIN_ID,
                text=admin_text,
                parse_mode="Markdown",
                reply_markup=get_moderation_keyboard(report_id)
            )
        elif media_type == "document" and file_id:
            await bot.send_document(
                chat_id=ADMIN_ID,
                document=file_id,
                caption=admin_text,
                parse_mode="Markdown",
                reply_markup=get_moderation_keyboard(report_id)
            )
        await message.answer("Жалоба отправлена на рассмотрение.")
    except Exception as e:
        await message.answer(f"Ошибка при отправке жалобы на проверку: {e}")

    await state.clear()


@dp.callback_query(F.data.startswith("approve_rep:"))
async def approve_report(callback: types.CallbackQuery):
    if not callback.from_user or callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет прав.", show_alert=True)
        return

    report_id = callback.data.split(":", 1)[1]
    rep = pending_reports.get(report_id)
    if not rep:
        await callback.answer("Жалоба уже обработана или не найдена.", show_alert=True)
        return

    channel_post = (
        "🚨 **ПОДТВЕРЖДЁННАЯ ЖАЛОБА**\n\n"
        f"👤 **Нарушитель:** {rep['target']}\n"
        f"📨 **Отправитель:** {rep['sender_info']} (`{rep['sender_id']}`)\n"
        f"📝 **Описание:** {rep['description']}"
    )

    try:
        media_type = rep.get("media_type")
        file_id = rep.get("file_id")
        if media_type == "photo" and file_id:
            await bot.send_photo(
                chat_id=REPORTS_CHANNEL_ID,
                photo=file_id,
                caption=channel_post,
                parse_mode="Markdown"
            )
        elif media_type == "video" and file_id:
            await bot.send_video(
                chat_id=REPORTS_CHANNEL_ID,
                video=file_id,
                caption=channel_post,
                parse_mode="Markdown"
            )
        elif media_type == "voice" and file_id:
            await bot.send_voice(
                chat_id=REPORTS_CHANNEL_ID,
                voice=file_id,
                caption=channel_post,
                parse_mode="Markdown"
            )
        elif media_type == "video_note" and file_id:
            await bot.send_video_note(
                chat_id=REPORTS_CHANNEL_ID,
                video_note=file_id
            )
            await bot.send_message(
                chat_id=REPORTS_CHANNEL_ID,
                text=channel_post,
                parse_mode="Markdown"
            )
        elif media_type == "document" and file_id:
            await bot.send_document(
                chat_id=REPORTS_CHANNEL_ID,
                document=file_id,
                caption=channel_post,
                parse_mode="Markdown"
            )

        pending_reports.pop(report_id, None)
        save_json(PENDING_FILE, pending_reports)

        updated_text = (callback.message.caption or callback.message.text or "") + "\n\n✅ **Подтверждено и отправлено в канал**"
        if callback.message.caption is not None:
            await callback.message.edit_caption(caption=updated_text, parse_mode="Markdown", reply_markup=None)
        else:
            await callback.message.edit_text(text=updated_text, parse_mode="Markdown", reply_markup=None)
        await callback.answer("Опубликовано в канал!")
    except Exception as e:
        await callback.answer(f"Ошибка публикации: {e}", show_alert=True)


@dp.callback_query(F.data.startswith("reject_rep:"))
async def reject_report(callback: types.CallbackQuery):
    if not callback.from_user or callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет прав.", show_alert=True)
        return

    report_id = callback.data.split(":", 1)[1]
    pending_reports.pop(report_id, None)
    save_json(PENDING_FILE, pending_reports)

    updated_text = (callback.message.caption or callback.message.text or "") + "\n\n❌ **Жалоба отклонена**"
    if callback.message.caption is not None:
        await callback.message.edit_caption(caption=updated_text, parse_mode="Markdown", reply_markup=None)
    else:
        await callback.message.edit_text(text=updated_text, parse_mode="Markdown", reply_markup=None)
    await callback.answer("Жалоба отклонена.")


@dp.callback_query(F.data == "stats")
async def show_stats(callback: types.CallbackQuery):
    if not callback.from_user or callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return
    await callback.message.edit_text(
        f"Записей в базе: {len(scammers_db)}",
        reply_markup=get_admin_inline_menu()
    )
    await callback.answer()


@dp.callback_query(F.data == "list_scammers")
async def show_list(callback: types.CallbackQuery):
    if not callback.from_user or callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return

    if not scammers_db:
        text = "База пуста."
    else:
        lines = []
        for target, info in list(scammers_db.items())[:15]:
            reason = info.get("reason", "-") if isinstance(info, dict) else str(info)
            lines.append(f"• {target} — {reason}")
        text = "\n".join(lines)

    builder = InlineKeyboardBuilder()
    builder.button(text="Назад", callback_data="back_menu")

    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


@dp.callback_query(F.data == "back_menu")
async def back_to_menu(callback: types.CallbackQuery):
    if not callback.from_user or callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return
    await callback.message.edit_text("Панель администратора:", reply_markup=get_admin_inline_menu())
    await callback.answer()


@dp.message(
    F.text
    & (
        F.text.lower().startswith("репорт")
        | F.text.lower().startswith("жалоба")
        | F.text.startswith("/add")
    )
)
async def handle_admin_add(message: types.Message):
    if not message.from_user or message.from_user.id != ADMIN_ID:
        return

    text = message.text.strip()
    for prefix in ["репорт", "жалоба", "/add"]:
        if text.lower().startswith(prefix):
            text = text[len(prefix):].strip()
            break

    args = text.split("|")
    if len(args) < 2:
        await message.reply("Формат: репорт <@username / id> | <причина> [| пруфы]")
        return

    target = args[0].strip()
    reason = args[1].strip()
    proof = args[2].strip() if len(args) > 2 else "-"

    scammers_db[target] = {"reason": reason, "proof": proof}
    save_json(DATA_FILE, scammers_db)
    await message.reply(f"Добавлено: {target}")


@dp.message(F.document)
async def handle_db_file(message: types.Message):
    if not message.from_user or message.from_user.id != ADMIN_ID:
        return

    doc = message.document
    if not doc.file_name or not doc.file_name.endswith(".json"):
        await message.reply("Нужен файл .json")
        return

    file_info = await bot.get_file(doc.file_id)
    downloaded = await bot.download_file(file_info.file_path)

    try:
        raw_text = downloaded.read().decode("utf-8")
        new_data = json.loads(raw_text)
        if not isinstance(new_data, dict):
            await message.reply("Неверный формат JSON.")
            return

        global scammers_db
        scammers_db = new_data
        save_json(DATA_FILE, scammers_db)
        await message.reply(f"База загружена. Записей: {len(scammers_db)}")
    except Exception as e:
        await message.reply(f"Ошибка: {e}")


@dp.message(F.text)
async def check_scammer(message: types.Message):
    if not message.text:
        return

    raw = message.text.strip()
    if raw.startswith("/") or "|" in raw:
        return

    target = extract_target(raw)
    if not target:
        return

    query = target.lower()
    found_key = None
    found_entry = None

    for key, val in scammers_db.items():
        if key.lower() == query:
            found_key = key
            found_entry = val
            break
        if isinstance(val, dict) and str(val.get("id", "")).lower() == query:
            found_key = key
            found_entry = val
            break

    if found_key:
        reason = found_entry.get("reason", "Не указана") if isinstance(found_entry, dict) else str(found_entry)
        id_line = resolve_display_id(found_key, message, found_entry)
        await message.reply(
            f"⚠️ **ВНИМАНИЕ! ЭТО СКАМ!**\n\n"
            f"👤 **Пользователь:** {found_key}\n"
            f"🆔 **ID:** {id_line}\n"
            f"❌ **Статус:** НАЙДЕН В БАЗЕ СКАМА\n"
            f"📝 **Причина:** {reason}",
            parse_mode="Markdown"
        )
    else:
        id_line = resolve_display_id(target, message, None)
        await message.reply(
            f"✅ **ПРОВЕРКА ПРОЙДЕНА**\n\n"
            f"👤 **Пользователь:** {target}\n"
            f"🆔 **ID:** {id_line}\n"
            f"ℹ️ **Статус:** В базе скама отсутствует.",
            parse_mode="Markdown"
        )


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