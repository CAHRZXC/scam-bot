import asyncio
import logging
import os
import sys
import json
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, BotCommand, FSInputFile
from aiohttp import web

TOKEN = '8802626648:AAHnsQSFsY8gT9LItYaJmCCX2B6ZxsMtOZY'
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

async def save_and_backup_data(bot: Bot):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(scammers_db, f, ensure_ascii=False, indent=4)
    
    try:
        file = FSInputFile(DATA_FILE)
        await bot.send_document(ADMIN_ID, document=file, caption="💾 Автоматический бэкап базы скамеров")
    except Exception as e:
        print(f"Ошибка отправки бэкапа: {e}")

scammers_db = load_local_data()
known_users = {}
pending_reports = {}
bot_instance = None

class ReportState(StatesGroup):
    waiting_for_photos = State()

class RejectState(StatesGroup):
    waiting_for_reason = State()

class RemoveState(StatesGroup):
    waiting_for_reason = State()

dp = Dispatcher(storage=MemoryStorage())

# Восстановление базы данных, если админ скинул файл в чат
@dp.message(F.from_user.id == ADMIN_ID, F.document)
async def restore_database(message: types.Message, bot: Bot):
    if message.document.file_name == 'scammers.json':
        file_info = await bot.get_file(message.document.file_id)
        await bot.download(file_info, destination=DATA_FILE)
        global scammers_db
        scammers_db = load_local_data()
        await message.answer("✅ База данных успешно восстановлена из файла :)")

@dp.message(Command('start'))
async def cmd_start(message: types.Message):
    if message.chat.type == 'private':
        text = (
            "Привет! Я бот **Scam ID**.\n\n"
            "• Чтобы проверить человека, отправь его `@username` или сделай **Reply (Ответ)** на его сообщение в группе.\n"
            "• Чтобы подать жалобу, напиши: `/report @username Причина`"
        )
        if message.from_user.id == ADMIN_ID:
            text += "\n\n👑 **Панель админа:** Напиши /panel для управления жалобами."
        await message.answer(text)

@dp.message(Command('panel'))
async def cmd_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    kb_buttons = [
        [InlineKeyboardButton(text=f"📩 Активные жалобы ({len(pending_reports)})", callback_data="view_pending")]
    ]
    
    if scammers_db:
        kb_buttons.append([InlineKeyboardButton(text="--- ❌ Список скамеров в базе ---", callback_data="ignore")])
        for target in list(scammers_db.keys())[:15]:
            kb_buttons.append([InlineKeyboardButton(text=f"@{target}", callback_data=f"scam_info_{target}")])

    kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
    await message.answer("⚙️ **Панель управления админа:**\nВыбери скамера из списка ниже, чтобы посмотреть его жалобу и доказательства:", reply_markup=kb)

@dp.callback_query(F.data.startswith('scam_info_'))
async def show_scammer_details(call: types.CallbackQuery, bot: Bot):
    if call.from_user.id != ADMIN_ID:
        return

    target = call.data.replace('scam_info_', '')
    if target in scammers_db:
        data = scammers_db[target]
        user_id_str = str(known_users.get(target, "Неизвестный"))
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Удалить из базы", callback_data=f"rem_{target}")]
        ])
        
        text = (
            f"⛔ **Информация о скамере:**\n\n"
            f"👤 **Юзернейм:** @{target}\n"
            f"🆔 **ID:** `{user_id_str}`\n"
            f"📝 **Причина:** {data.get('reason', 'Не указано')}\n"
            f"👤 **Репортер ID:** `{data.get('reported_by', 'Админ')}`"
        )

        voice_id = data.get('voice_id')
        if voice_id:
            try:
                await bot.send_voice(ADMIN_ID, voice=voice_id, caption="🎤 Голосовое доказательство")
            except Exception:
                pass

        photo_ids = data.get('photo_ids', [])
        if photo_ids:
            if len(photo_ids) > 1:
                media = [InputMediaPhoto(media=photo_ids[0])]
                for pid in photo_ids[1:]:
                    media.append(InputMediaPhoto(media=pid))
                try:
                    await bot.send_media_group(ADMIN_ID, media=media)
                    await bot.send_message(ADMIN_ID, text=text, reply_markup=kb)
                except Exception:
                    await bot.send_message(ADMIN_ID, text=text, reply_markup=kb)
            else:
                try:
                    await bot.send_photo(ADMIN_ID, photo=photo_ids[0], caption=text, reply_markup=kb)
                except Exception:
                    await bot.send_message(ADMIN_ID, text=text, reply_markup=kb)
        else:
            await bot.send_message(ADMIN_ID, text=text, reply_markup=kb)
            
    await call.answer()

@dp.callback_query(F.data == "ignore")
async def ignore_callback(call: types.CallbackQuery):
    await call.answer()

@dp.callback_query(F.data == "view_pending")
async def view_pending_reports(call: types.CallbackQuery, bot: Bot):
    if call.from_user.id != ADMIN_ID:
        return

    if not pending_reports:
        await call.message.answer("📩 Нет активных жалоб в очереди.")
        await call.answer()
        return

    for report_id, data in list(pending_reports.items()):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"app_{report_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"rej_{report_id}")
            ]
        ])
        report_text = (
            f"📋 **Жалоба в очереди:**\n\n"
            f"👤 **От кого:** {data['reporter_name']} (`{data['reporter_id']}`)\n"
            f"🎯 **На кого:** {data['target']}\n"
            f"📝 **Причина:** {data['reason']}"
        )

        voice_id = data.get('voice_id')
        if voice_id:
            try:
                await bot.send_voice(ADMIN_ID, voice=voice_id, caption="🎤 Голосовое сообщение от репортера")
            except Exception:
                pass

        photo_ids = data.get('photo_ids', [])
        if photo_ids:
            if len(photo_ids) > 1:
                media = [InputMediaPhoto(media=photo_ids[0])]
                for pid in photo_ids[1:]:
                    media.append(InputMediaPhoto(media=pid))
                try:
                    await bot.send_media_group(ADMIN_ID, media=media)
                    await bot.send_message(ADMIN_ID, text=report_text, reply_markup=kb)
                except Exception:
                    await bot.send_message(ADMIN_ID, text=report_text, reply_markup=kb)
            else:
                try:
                    await bot.send_photo(ADMIN_ID, photo=photo_ids[0])
                    await bot.send_message(ADMIN_ID, text=report_text, reply_markup=kb)
                except Exception:
                    await bot.send_message(ADMIN_ID, text=report_text, reply_markup=kb)
        else:
            await bot.send_message(ADMIN_ID, text=report_text, reply_markup=kb)
    await call.answer()

@dp.message(Command('report'))
async def cmd_report(message: types.Message, command: CommandObject, state: FSMContext):
    caption_or_text = message.caption or message.text or ""
    words = caption_or_text.split()

    raw_usernames = [w.replace(',', '').strip() for w in words if w.startswith('@')]

    if not raw_usernames:
        await message.answer("Ошибка! Укажи юзернейм нарушителя через @, например: `/report @username Причина`")
        return

    clean_targets = [u.replace('@', '').replace('https://t.me/', '').replace('t.me/', '').lower() for u in raw_usernames]
    formatted_target = ", ".join([f"@{t}" for t in clean_targets])

    reason_parts = [w for w in words if w != '/report' and w.replace(',', '').strip() not in raw_usernames]
    reason = " ".join(reason_parts).strip()
    if not reason:
        reason = "Без причины"

    await state.update_data(target=formatted_target, clean_targets=clean_targets, reason=reason, photo_ids=[], voice_id=None)
    await state.set_state(ReportState.waiting_for_photos)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Готово (Отправить жалобу)", callback_data="finish_report")]
    ])

    await message.answer(
        f"🎯 Нарушители: **{formatted_target}**\n"
        f"📝 Причина: {reason}\n\n"
        "📸 Теперь отправь скриншоты-доказательства или 🎤 **голосовое сообщение**.\n"
        "Когда закончишь, нажми кнопку **«Готово»** ниже:",
        reply_markup=kb
    )

@dp.message(ReportState.waiting_for_photos, F.photo)
async def process_report_photos(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    photo_ids = user_data.get('photo_ids', [])
    photo_ids.append(message.photo[-1].file_id)
    await state.update_data(photo_ids=photo_ids)

@dp.message(ReportState.waiting_for_photos, F.voice)
async def process_report_voice(message: types.Message, state: FSMContext):
    await state.update_data(voice_id=message.voice.file_id)
    await message.answer("🎤 Голосовое сообщение принято! Можешь докинуть скриншоты или нажать кнопку **«Готово»**.")

@dp.callback_query(ReportState.waiting_for_photos, F.data == "finish_report")
async def finish_report_callback(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    user_data = await state.get_data()
    target = user_data['target']
    clean_targets = user_data.get('clean_targets', [])
    reason = user_data['reason']
    photo_ids = user_data.get('photo_ids', [])
    voice_id = user_data.get('voice_id')

    report_id = f"{call.from_user.id}_{clean_targets[0] if clean_targets else 'scam'}"
    data = {
        'target': target,
        'clean_targets': clean_targets,
        'reason': reason,
        'reporter_id': call.from_user.id,
        'reporter_name': call.from_user.full_name,
        'photo_ids': photo_ids,
        'voice_id': voice_id
    }

    pending_reports[report_id] = data

    report_text = (
        f"📩 **НОВАЯ ЖАЛОБА!**\n\n"
        f"👤 **От кого:** {data['reporter_name']} (`{data['reporter_id']}`)\n"
        f"🎯 **На кого:** {data['target']}\n"
        f"📝 **Причина:** {data['reason']}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"app_{report_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"rej_{report_id}")
        ]
    ])

    if voice_id:
        try:
            await bot.send_voice(ADMIN_ID, voice=voice_id, caption="🎤 Голосовое сообщение от репортера")
        except Exception:
            pass

    if photo_ids:
        if len(photo_ids) > 1:
            media = [InputMediaPhoto(media=photo_ids[0])]
            for pid in photo_ids[1:]:
                media.append(InputMediaPhoto(media=pid))
            try:
                await bot.send_media_group(ADMIN_ID, media=media)
            except Exception:
                pass
        else:
            try:
                await bot.send_photo(ADMIN_ID, photo=photo_ids[0])
            except Exception:
                pass

    await bot.send_message(ADMIN_ID, text=report_text, reply_markup=kb)

    try:
        await call.message.edit_text("🎉 Ваша жалоба со всеми доказательствами успешно отправлена администратору на проверку!")
    except Exception:
        pass

    await state.clear()
    await call.answer()

@dp.callback_query(F.data.startswith('app_'))
async def approve_report(call: types.CallbackQuery, bot: Bot):
    if call.from_user.id != ADMIN_ID:
        return

    report_id = call.data.replace('app_', '')
    if report_id in pending_reports:
        data = pending_reports.pop(report_id)

        clean_targets = data.get('clean_targets', [])
        if not clean_targets and 'target' in data:
            clean_targets = [t.strip().replace('@', '') for t in data['target'].split(',')]

        for t in clean_targets:
            scammers_db[t] = {
                'reason': data['reason'],
                'reported_by': data['reporter_id'],
                'photo_ids': data.get('photo_ids', []),
                'voice_id': data.get('voice_id')
            }

        await save_and_backup_data(bot)

        try:
            await call.message.edit_text(text=f"✅ Жалоба на {data['target']} **ПОДТВЕРЖДЕНА** и все нарушители добавлены в базу!")
        except Exception:
            try:
                await call.message.edit_caption(caption=f"✅ Жалоба на {data['target']} **ПОДТВЕРЖДЕНА** и все нарушители добавлены в базу!")
            except Exception:
                pass

        try:
            await bot.send_message(data['reporter_id'], f"🎉 Ваша жалоба на {data['target']} подтверждена :)")
        except Exception:
            pass
    await call.answer()

@dp.callback_query(F.data.startswith('rej_'))
async def reject_report_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return

    report_id = call.data.replace('rej_', '')
    if report_id in pending_reports:
        await state.update_data(reject_report_id=report_id)
        await state.set_state(RejectState.waiting_for_reason)
        await call.message.answer("Введите причину отклонения жалобы:")
    await call.answer()

@dp.message(RejectState.waiting_for_reason)
async def process_reject_reason(message: types.Message, state: FSMContext, bot: Bot):
    if message.from_user.id != ADMIN_ID:
        return

    user_data = await state.get_data()
    report_id = user_data.get('reject_report_id')

    if report_id in pending_reports:
        data = pending_reports.pop(report_id)
        reject_reason = message.text

        await message.answer(f"❌ Жалоба на {data['target']} отклонена.")
        try:
            await bot.send_message(
                data['reporter_id'],
                f"❌ Ваша жалоба на {data['target']} отклонена.\n📝 **Причина:** {reject_reason}"
            )
        except Exception:
            pass

    await state.clear()

@dp.callback_query(F.data.startswith('rem_'))
async def remove_scammer_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return

    target = call.data.replace('rem_', '')
    if target in scammers_db:
        await state.update_data(remove_target=target)
        await state.set_state(RemoveState.waiting_for_reason)
        await call.message.answer(f"Введите причину удаления @{target} из баз скамеров:")
    await call.answer()

@dp.message(RemoveState.waiting_for_reason)
async def process_remove_reason(message: types.Message, state: FSMContext, bot: Bot):
    if message.from_user.id != ADMIN_ID:
        return

    user_data = await state.get_data()
    target = user_data.get('remove_target')

    if target in scammers_db:
        data = scammers_db.pop(target)
        await save_and_backup_data(bot)
        remove_reason = message.text

        await message.answer(f"🗑 Пользователь @{target} успешно удален из баз скамеров.")

        reporter_id = data.get('reported_by')
        if reporter_id and str(reporter_id).isdigit():
            try:
                await bot.send_message(
                    int(reporter_id),
                    f"ℹ️ Статус вашей жалобы на @{target} был отменен админом.\n📝 **Причина удаления:** {remove_reason}"
                )
            except Exception:
                pass

    await state.clear()

@dp.message(F.chat.type.in_({'group', 'supergroup'}))
async def check_in_group(message: types.Message, bot: Bot):
    if ALLOWED_GROUP_ID != 0 and message.chat.id != ALLOWED_GROUP_ID:
        return

    if message.from_user and message.from_user.username:
        uname = message.from_user.username.lower()
        if uname not in known_users:
            known_users[uname] = message.from_user.id

    if message.reply_to_message and message.text and (message.text.startswith('@') or message.text.lower() == 'скам'):
        target_user = message.reply_to_message.from_user
        target_username = target_user.username.lower() if target_user.username else "нет"
        target_id = target_user.id

        if target_username in scammers_db:
            scam_data = scammers_db[target_username]
            reason = scam_data.get('reason', 'Не указано')
            photo_ids = scam_data.get('photo_ids', [])
            voice_id = scam_data.get('voice_id')

            warning_text = (
                f"⚠️ **ВНИМАНИЕ! ЭТО СКАМЕР!**\n\n"
                f"👤 **Пользователь:** @{target_username}\n"
                f"🆔 **ID:** `{target_id}`\n"
                f"❌ **Статус:** НАЙДЕН В БАЗЕ СКАМА\n"
                f"📝 **Причина:** {reason}"
            )

            if voice_id:
                try:
                    await message.reply_voice(voice=voice_id, caption="🎤 Голосовое доказательство")
                except Exception:
                    pass

            if photo_ids:
                if len(photo_ids) > 1:
                    media = [InputMediaPhoto(media=photo_ids[0])]
                    for pid in photo_ids[1:]:
                        media.append(InputMediaPhoto(media=pid))
                    try:
                        await message.reply_media_group(media=media)
                        await message.reply(warning_text)
                    except Exception:
                        await message.reply(warning_text)
                else:
                    await message.reply_photo(photo=photo_ids[0], caption=warning_text)
            else:
                await message.reply(warning_text)
        else:
            await message.reply(
                f"✅ **ПРОВЕРКА ПРОЙДЕНА**\n\n"
                f"👤 **Пользователь:** @{target_username}\n"
                f"🆔 **ID:** `{target_id}`\n"
                f"ℹ️ **Статус:** В базе скама отсутствует."
            )
        return

    text = message.text or message.caption or ""
    if text.startswith('@') or 't.me/' in text:
        target = text.strip().replace('@', '').replace('https://t.me/', '').replace('t.me/', '').lower()

        user_id_str = str(known_users.get(target, "Скрыт (еще не писал в группе)"))

        if user_id_str.startswith("Скрыт"):
            try:
                chat_info = await bot.get_chat(f"@{target}")
                user_id_str = str(chat_info.id)
            except Exception:
                pass

        if target in scammers_db:
            scam_data = scammers_db[target]
            reason = scam_data.get('reason', 'Не указано')
            photo_ids = scam_data.get('photo_ids', [])
            voice_id = scam_data.get('voice_id')

            warning_text = (
                f"⚠️ **ВНИМАНИЕ! ЭТО СКАМЕР!**\n\n"
                f"👤 **Пользователь:** @{target}\n"
                f"🆔 **ID:** `{user_id_str}`\n"
                f"❌ **Статус:** НАЙДЕН В БАЗЕ СКАМА\n"
                f"📝 **Причина:** {reason}"
            )

            if voice_id:
                try:
                    await message.reply_voice(voice=voice_id, caption="🎤 Голосовое доказательство")
                except Exception:
                    pass

            if photo_ids:
                if len(photo_ids) > 1:
                    media = [InputMediaPhoto(media=photo_ids[0])]
                    for pid in photo_ids[1:]:
                        media.append(InputMediaPhoto(media=pid))
                    try:
                        await message.reply_media_group(media=media)
                        await message.reply(warning_text)
                    except Exception:
                        await message.reply(warning_text)
                else:
                    await message.reply_photo(photo=photo_ids[0], caption=warning_text)
            else:
                await message.reply(warning_text)
        else:
            await message.reply(
                f"✅ **ПРОВЕРКА ПРОЙДЕНА**\n\n"
                f"👤 **Пользователь:** @{target}\n"
                f"🆔 **ID:** `{user_id_str}`\n"
                f"ℹ️ **Статус:** В базе скама отсутствует."
            )

async def set_bot_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="report", description="Подать жалобу на скамера"),
        BotCommand(command="panel", description="Панель администратора")
    ]
    await bot.set_my_commands(commands)

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
    global bot_instance
    bot = Bot(token=TOKEN)
    bot_instance = bot
    
    await set_bot_commands(bot)
    asyncio.create_task(web_server())
    await dp.start_polling(bot)

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())