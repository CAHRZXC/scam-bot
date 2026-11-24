import os
import re
import json
import asyncio
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

TOKEN = "8802626648:AAHYegmfNfmTSQoXIYkLL3Mu3Ok-QrEZI2Q"
ADMIN_ID = 8405165103
REPORTS_CHANNEL_ID = -1003725925366
CHANNEL_LINK = "https://t.me/+cowjUfhNz6kzMjNh"

DATA_FILE = "scammers.json"
PENDING_FILE = "pending_reports.json"

LINK_PATTERN = re.compile(r"(https?://\S+|t\.me/\S+|www\.\S+)", re.IGNORECASE)


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
logger = logging.getLogger("scam_bot")

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


def get_view_report_keyboard(post_url: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="Смотреть жалобу ↗", url=post_url)
    builder.adjust(1)
    return builder.as_markup()


def build_channel_post_link(chat_id: int, message_id: int):
    raw_id = str(chat_id)
    if raw_id.startswith("-100"):
        internal_id = raw_id[4:]
        return f"https://t.me/c/{internal_id}/{message_id}"
    return CHANNEL_LINK


def extract_link(text: str):
    if not text:
        return None
    match = LINK_PATTERN.search(text.strip())
    if not match:
        return None
    url = match.group(0).rstrip(".,!?)];\"'")
    if url.lower().startswith(("t.me/", "www.")):
        url = "https://" + url
    return url


def extract_target(text: str):
    if not text:
        return None
    username_match = re.search(r"@[A-Za-z0-9_]{2,}", text)
    if username_match:
        return username_match.group(0)
    id_match = re.search(r"\b\d{5,15}\b", text)
    if id_match:
        return id_match.group(0)
    return None


def resolve_display_id(target: str, message: types.Message, db_entry):
    if isinstance(db_entry, dict) and db_entry.get("id"):
        return f"<code>{db_entry['id']}</code>"
    if target.isdigit():
        return f"<code>{target}</code>"
    if message.reply_to_message and message.reply_to_message.from_user:
        rep_user = message.reply_to_message.from_user
        if rep_user.username and f"@{rep_user.username.lower()}" == target.lower():
            return f"<code>{rep_user.id}</code>"
    return "<code>Скрыт (еще не писал в группе)</code>"


def add_scammer_to_db(raw_target: str, reason: str, proof: str = "-", post_link: str = None):
    extracted = extract_target(raw_target) or raw_target.strip()
    key = extracted
    scammer_id = extracted if extracted.isdigit() else None

    existing = scammers_db.get(key)
    final_post_link = post_link or (existing.get("post_link") if isinstance(existing, dict) else None) or CHANNEL_LINK

    scammers_db[key] = {
        "reason": reason,
        "proof": proof,
        "id": scammer_id,
        "post_link": final_post_link,
    }
    save_json(DATA_FILE, scammers_db)
    return key


def find_scammer_entry(target: str):
    query = target.lower()
    for key, val in scammers_db.items():
        if key.lower() == query:
            return key, val
        if isinstance(val, dict) and str(val.get("id", "")).lower() == query:
            return key, val
    return None, None


async def send_scammer_report_card(chat_id: int, found_key: str, found_entry):
    reason = found_entry.get("reason", "Не указана") if isinstance(found_entry, dict) else str(found_entry)
    scammer_id = found_entry.get("id") if isinstance(found_entry, dict) else None
    post_link = (found_entry.get("post_link") if isinstance(found_entry, dict) else None) or CHANNEL_LINK
    id_display = f"<code>{scammer_id}</code>" if scammer_id else "<code>Не указан</code>"

    text = (
        f"⚠️ <b>ВНИМАНИЕ! ЭТО СКАМ!</b>\n\n"
        f"👤 <b>Пользователь:</b> {found_key}\n"
        f"🆔 {id_display}\n"
        f"❌ <b>Статус:</b> НАЙДЕН В БАЗЕ СКАМА\n"
        f"📝 <b>Причина:</b> {reason}"
    )
    await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",
        reply_markup=get_view_report_keyboard(post_link)
    )


@dp.message(CommandStart(deep_link=True))
async def cmd_start_deeplink(message: types.Message, state: FSMContext, command: CommandStart):
    await state.clear()
    args = (command.args or "").strip()

    if args.startswith("rep_"):
        raw_query = args[4:].replace("_", " ").strip()
        found_key, found_entry = find_scammer_entry(raw_query)
        if not found_key and not raw_query.startswith("@") and raw_query.isalnum():
            found_key, found_entry = find_scammer_entry("@" + raw_query)

        if found_key:
            await send_scammer_report_card(message.chat.id, found_key, found_entry)
            return

    await message.answer(
        "Бот проверки пользователей и приёма жалоб.\n"
        "В группах просто отправь @username или ID — я проверю по базе.\n"
        f'Канал с жалобами: <a href="{CHANNEL_LINK}">перейти в канал</a>',
        parse_mode="HTML",
        reply_markup=get_reply_menu() if message.chat.type == "private" else None
    )
    if message.from_user and message.from_user.id == ADMIN_ID:
        await message.answer("Панель администратора:", reply_markup=get_admin_inline_menu())


@dp.message(Command("start", "menu"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    if message.chat.type == "private":
        await message.answer(
            "Бот проверки пользователей и приёма жалоб.\n"
            "В группах просто отправь @username или ID — я проверю по базе.\n"
            f'Канал с жалобами: <a href="{CHANNEL_LINK}">перейти в канал</a>',
            parse_mode="HTML",
            reply_markup=get_reply_menu()
        )
    if message.from_user and message.from_user.id == ADMIN_ID:
        await message.answer("Панель администратора:", reply_markup=get_admin_inline_menu())


@dp.message(F.text == "Что за бот")
async def btn_about(message: types.Message):
    await message.answer(
        "Бот проверяет пользователей и ID по базе скамеров.\n"
        "Чтобы подать жалобу — нажми «Подать жалобу» или напиши /report.\n"
        f'Канал с жалобами: <a href="{CHANNEL_LINK}">перейти в канал</a>',
        parse_mode="HTML",
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

    raw_text = message.caption or message.text or ""
    proof_link = extract_link(raw_text)

    if not media_type and not proof_link:
        await message.answer("Жалобы без пруфов не принимаются")
        return

    data = await state.get_data()
    target = data.get("report_target", "Не указан")
    sender = message.from_user
    sender_id = sender.id if sender else 0
    sender_info = f"@{sender.username}" if sender and sender.username else f"ID {sender_id}"
    description = raw_text.strip() if raw_text.strip() else "(без текстового описания)"

    report_id = str(message.message_id) + f"_{sender_id}"

    pending_reports[report_id] = {
        "target": target,
        "sender_info": sender_info,
        "sender_id": sender_id,
        "description": description,
        "proof_link": proof_link,
        "media_type": media_type,
        "file_id": file_id,
    }
    save_json(PENDING_FILE, pending_reports)

    admin_text = (
        "🚨 <b>НОВАЯ ЖАЛОБА НА ПРОВЕРКУ</b>\n\n"
        f"👤 <b>Нарушитель:</b> {target}\n"
        f"📨 <b>Отправитель:</b> {sender_info} (<code>{sender_id}</code>)\n"
        f"📝 <b>Описание:</b> {description}"
    )

    try:
        if media_type == "photo" and file_id:
            await bot.send_photo(
                chat_id=ADMIN_ID,
                photo=file_id,
                caption=admin_text,
                parse_mode="HTML",
                reply_markup=get_moderation_keyboard(report_id)
            )
        elif media_type == "video" and file_id:
            await bot.send_video(
                chat_id=ADMIN_ID,
                video=file_id,
                caption=admin_text,
                parse_mode="HTML",
                reply_markup=get_moderation_keyboard(report_id)
            )
        elif media_type == "voice" and file_id:
            await bot.send_voice(
                chat_id=ADMIN_ID,
                voice=file_id,
                caption=admin_text,
                parse_mode="HTML",
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
                parse_mode="HTML",
                reply_markup=get_moderation_keyboard(report_id)
            )
        elif media_type == "document" and file_id:
            await bot.send_document(
                chat_id=ADMIN_ID,
                document=file_id,
                caption=admin_text,
                parse_mode="HTML",
                reply_markup=get_moderation_keyboard(report_id)
            )
        else:
            await bot.send_message(
                chat_id=ADMIN_ID,
                text=admin_text,
                parse_mode="HTML",
                reply_markup=get_moderation_keyboard(report_id)
            )
        await message.answer(
            "Жалоба отправлена на рассмотрение.\n"
            f'Канал с жалобами: <a href="{CHANNEL_LINK}">открыть канал</a>',
            parse_mode="HTML"
        )
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
        "🚨 <b>ПОДТВЕРЖДЁННАЯ ЖАЛОБА</b>\n\n"
        f"👤 <b>Нарушитель:</b> {rep['target']}\n"
        f"📨 <b>Отправитель:</b> {rep['sender_info']} (<code>{rep['sender_id']}</code>)\n"
        f"📝 <b>Описание:</b> {rep['description']}"
    )

    try:
        media_type = rep.get("media_type")
        file_id = rep.get("file_id")
        sent_msg = None

        if media_type == "photo" and file_id:
            sent_msg = await bot.send_photo(
                chat_id=REPORTS_CHANNEL_ID,
                photo=file_id,
                caption=channel_post,
                parse_mode="HTML"
            )
        elif media_type == "video" and file_id:
            sent_msg = await bot.send_video(
                chat_id=REPORTS_CHANNEL_ID,
                video=file_id,
                caption=channel_post,
                parse_mode="HTML"
            )
        elif media_type == "voice" and file_id:
            sent_msg = await bot.send_voice(
                chat_id=REPORTS_CHANNEL_ID,
                voice=file_id,
                caption=channel_post,
                parse_mode="HTML"
            )
        elif media_type == "video_note" and file_id:
            await bot.send_video_note(
                chat_id=REPORTS_CHANNEL_ID,
                video_note=file_id
            )
            sent_msg = await bot.send_message(
                chat_id=REPORTS_CHANNEL_ID,
                text=channel_post,
                parse_mode="HTML"
            )
        elif media_type == "document" and file_id:
            sent_msg = await bot.send_document(
                chat_id=REPORTS_CHANNEL_ID,
                document=file_id,
                caption=channel_post,
                parse_mode="HTML"
            )
        else:
            sent_msg = await bot.send_message(
                chat_id=REPORTS_CHANNEL_ID,
                text=channel_post,
                parse_mode="HTML"
            )

        post_link = build_channel_post_link(REPORTS_CHANNEL_ID, sent_msg.message_id) if sent_msg else CHANNEL_LINK

        saved_key = add_scammer_to_db(
            raw_target=rep["target"],
            reason=rep["description"],
            proof=rep.get("proof_link") or f"report:{report_id}",
            post_link=post_link
        )

        pending_reports.pop(report_id, None)
        save_json(PENDING_FILE, pending_reports)

        updated_text = (
            (callback.message.caption or callback.message.text or "")
            + f"\n\n✅ <b>Подтверждено, отправлено в канал и добавлено в базу ({saved_key})</b>"
        )
        if callback.message.caption is not None:
            await callback.message.edit_caption(caption=updated_text, parse_mode="HTML", reply_markup=None)
        else:
            await callback.message.edit_text(text=updated_text, parse_mode="HTML", reply_markup=None)

        try:
            db_doc = FSInputFile(DATA_FILE, filename=DATA_FILE)
            await bot.send_document(
                chat_id=ADMIN_ID,
                document=db_doc,
                caption=f"Обновлённая база после добавления {saved_key} (записей: {len(scammers_db)})"
            )
        except Exception as doc_err:
            logger.error(f"Не удалось отправить файл базы {DATA_FILE}: {doc_err}")

        await callback.answer("Опубликовано, добавлено в базу и файл отправлен!")
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

    updated_text = (callback.message.caption or callback.message.text or "") + "\n\n❌ <b>Жалоба отклонена</b>"
    if callback.message.caption is not None:
        await callback.message.edit_caption(caption=updated_text, parse_mode="HTML", reply_markup=None)
    else:
        await callback.message.edit_text(text=updated_text, parse_mode="HTML", reply_markup=None)
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

    saved_key = add_scammer_to_db(target, reason, proof, post_link=CHANNEL_LINK)
    await message.reply(f"Добавлено: {saved_key}")


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
    if raw.startswith("/"):
        return

    if raw.lower().startswith(("репорт", "жалоба")) and "|" in raw:
        return

    target = extract_target(raw)
    if not target:
        return

    logger.info(f"Проверка цели '{target}' в чате {message.chat.id} от {message.from_user.id if message.from_user else 0}")

    found_key, found_entry = find_scammer_entry(target)

    if found_key:
        reason = found_entry.get("reason", "Не указана") if isinstance(found_entry, dict) else str(found_entry)
        id_line = resolve_display_id(found_key, message, found_entry)

        me = await bot.get_me()
        clean_code = re.sub(r"[^A-Za-z0-9_]", "", found_key.lstrip("@"))
        deep_link = f"https://t.me/{me.username}?start=rep_{clean_code}" if me.username and clean_code else CHANNEL_LINK

        reply_text = (
            f"⚠️ <b>ВНИМАНИЕ! ЭТО СКАМ!</b>\n\n"
            f"👤 <b>Пользователь:</b> {found_key}\n"
            f"🆔 {id_line}\n"
            f"❌ <b>Статус:</b> НАЙДЕН В БАЗЕ СКАМА\n"
            f"📝 <b>Причина:</b> {reason}\n"
            f'🔗 <a href="{deep_link}">Открыть жалобу в боте</a>'
        )
    else:
        id_line = resolve_display_id(target, message, None)
        reply_text = (
            f"✅ <b>ПРОВЕРКА ПРОЙДЕНА</b>\n\n"
            f"👤 <b>Пользователь:</b> {target}\n"
            f"🆔 {id_line}\n"
            f"ℹ️ <b>Статус:</b> В базе скама отсутствует."
        )

    try:
        await message.reply(reply_text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ошибка ответа на проверку '{target}': {e}")
        try:
            await message.answer(reply_text, parse_mode="HTML")
        except Exception as e2:
            logger.error(f"Повторная ошибка отправки ответа '{target}': {e2}")


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
    await dp.start_polling(bot, skip_updates=False)


if __name__ == "__main__":
    asyncio.run(main())