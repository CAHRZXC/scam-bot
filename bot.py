import asyncio
import logging
import os
import sys
import json
from telethon import TelegramClient, events, Button
from aiohttp import web

API_ID = 33569651
API_HASH = "b08d408fab7b2e38d6f7d5252f7b5eb7"
ADMIN_ID = 8405165103

DATA_FILE = 'scammers.json'
GROUPS_FILE = 'allowed_groups.json'

def load_json(filename, default):
    if os.path.exists(filename):
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return default

def save_json(filename, data):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

scammers_db = load_json(DATA_FILE, {})
allowed_groups = load_json(GROUPS_FILE, [])
pending_reports = {}

# Инициализируем клиента с твоими учетными данными
client = TelegramClient('userbot', API_ID, API_HASH)

async def save_and_backup_data():
    save_json(DATA_FILE, scammers_db)
    try:
        await client.send_file(ADMIN_ID, DATA_FILE, caption="💾 Автоматический бэкап базы скамеров :)")
    except Exception as e:
        print(f"Ошибка бэкапа: {e}")

@client.on(events.NewMessage(pattern='/start'))
async def cmd_start(event):
    if event.is_private:
        text = (
            "Привет! Я бот **Scam ID**.\n\n"
            "• Чтобы проверить человека, отправь его `@username` или сделай **Reply (Ответ)** на его сообщение в группе.\n"
            "• Чтобы подать жалобу, напиши: `/report @username Причина`"
        )
        if event.sender_id == ADMIN_ID:
            text += "\n\n👑 **Панель админа:** Напиши /panel для управления жалобами и группами."
        await event.respond(text)

@client.on(events.NewMessage(pattern='/panel', chats=ADMIN_ID))
async def cmd_panel(event):
    buttons = [
        [Button.inline(f"📩 Активные жалобы ({len(pending_reports)})", data="view_pending")],
        [Button.inline(f"🟢 Разрешенные группы ({len(allowed_groups)})", data="view_groups")],
        [Button.inline("➕ Добавить разрешенную группу", data="add_group_btn")]
    ]
    if scammers_db:
        buttons.append([Button.inline("--- ❌ Скамеры в базе ---", data="ignore")])
        for target in list(scammers_db.keys())[:15]:
            buttons.append([Button.inline(f"@{target}", data=f"scam_info_{target}")])

    await event.respond("⚙️ **Панель управления админа:**", buttons=buttons)

@client.on(events.CallbackQuery)
async def callback_handler(event):
    data = event.data.decode('utf-8')
    
    if data == "view_groups" and event.sender_id == ADMIN_ID:
        if not allowed_groups:
            await event.respond("📁 Список разрешенных групп пуст.")
        else:
            text = "🟢 **Разрешенные группы (ID):**\n\n" + "\n".join([f"• `{g}`" for g in allowed_groups])
            await event.respond(text)
        await event.answer()

    elif data == "add_group_btn" and event.sender_id == ADMIN_ID:
        async with client.conversation(ADMIN_ID) as conv:
            await conv.send_message("🔗 Отправь мне **ссылку на чат** или перешли сообщение из него:")
            response = await conv.get_response()
            
            target_chat = None
            if response.forward:
                target_chat = response.forward.chat_id
            else:
                try:
                    entity = await client.get_entity(response.text.strip())
                    target_chat = entity.id
                except Exception:
                    pass

            if target_chat:
                if target_chat not in allowed_groups:
                    allowed_groups.append(target_chat)
                    save_json(GROUPS_FILE, allowed_groups)
                    await conv.send_message(f"✅ Группа с ID `{target_chat}` успешно добавлена!")
                else:
                    await conv.send_message("ℹ️ Эта группа уже есть в списке.")
            else:
                await conv.send_message("❌ Не удалось найти группу.")
        await event.answer()

    elif data.startswith("scam_info_") and event.sender_id == ADMIN_ID:
        target = data.replace("scam_info_", "")
        if target in scammers_db:
            info = scammers_db[target]
            
            try:
                user_entity = await client.get_entity(target)
                real_id = user_entity.id
            except Exception:
                real_id = "Не найден"

            text = (
                f"⛔ **Информация о скамере:**\n\n"
                f"👤 **Юзернейм:** @{target}\n"
                f"🆔 **ID:** `{real_id}`\n"
                f"📝 **Причина:** {info.get('reason', 'Не указано')}\n"
                f"👤 **Репортер ID:** `{info.get('reported_by', 'Админ')}`"
            )
            buttons = [[Button.inline("🗑 Удалить из базы", data=f"rem_{target}")]]
            await event.respond(text, buttons=buttons)
        await event.answer()

    elif data == "view_pending" and event.sender_id == ADMIN_ID:
        if not pending_reports:
            await event.respond("📩 Нет активных жалоб в очереди.")
            await event.answer()
            return
        
        for report_id, report_data in list(pending_reports.items()):
            r_text = (
                f"📋 **Жалоба в очереди:**\n\n"
                f"👤 **От кого:** {report_data['reporter_name']} (`{report_data['reporter_id']}`)\n"
                f"🎯 **На кого:** {report_data['target']}\n"
                f"📝 **Причина:** {report_data['reason']}"
            )
            r_buttons = [
                [
                    Button.inline("✅ Подтвердить", data=f"app_{report_id}"),
                    Button.inline("❌ Отклонить", data=f"rej_{report_id}")
                ]
            ]
            await event.respond(r_text, buttons=r_buttons)
        await event.answer()

    elif data.startswith("app_") and event.sender_id == ADMIN_ID:
        report_id = data.replace("app_", "")
        if report_id in pending_reports:
            report_data = pending_reports.pop(report_id)
            for t in report_data['clean_targets']:
                scammers_db[t] = {
                    'reason': report_data['reason'],
                    'reported_by': report_data['reporter_id']
                }
            await save_and_backup_data()
            await event.respond(f"✅ Жалоба на {report_data['target']} подтверждена :)")
        await event.answer()

    elif data.startswith("rem_") and event.sender_id == ADMIN_ID:
        target = data.replace("rem_", "")
        if target in scammers_db:
            scammers_db.pop(target)
            await save_and_backup_data()
            await event.respond(f"🗑 Пользователь @{target} удален из базы.")
        await event.answer()

@client.on(events.NewMessage(pattern='/report'))
async def cmd_report(event):
    words = event.text.split()
    raw_usernames = [w.replace(',', '').strip() for w in words if w.startswith('@')]

    if not raw_usernames:
        await event.respond("Ошибка! Укажи юзернейм через @: `/report @username Причина`")
        return

    clean_targets = [u.replace('@', '').lower() for u in raw_usernames]
    reason = " ".join([w for w in words if w != '/report' and not w.startswith('@')]).strip() or "Без причины"
    
    report_id = f"{event.sender_id}_{clean_targets[0]}"
    pending_reports[report_id] = {
        'target': ", ".join([f"@{t}" for t in clean_targets]),
        'clean_targets': clean_targets,
        'reason': reason,
        'reporter_id': event.sender_id,
        'reporter_name': event.sender.first_name if event.sender else "Пользователь"
    }

    report_text = (
        f"📩 **НОВАЯ ЖАЛОБА!**\n\n"
        f"👤 **От кого:** {pending_reports[report_id]['reporter_name']} (`{event.sender_id}`)\n"
        f"🎯 **На кого:** {pending_reports[report_id]['target']}\n"
        f"📝 **Причина:** {reason}"
    )
    
    buttons = [
        [
            Button.inline("✅ Подтвердить", data=f"app_{report_id}"),
            Button.inline("❌ Отклонить", data=f"rej_{report_id}")
        ]
    ]
    await client.send_message(ADMIN_ID, report_text, buttons=buttons)
    await event.respond("🎉 Ваша жалоба отправлена администратору!")

@client.on(events.NewMessage)
async def check_group_message(event):
    if not event.is_group and not event.is_channel:
        return

    if allowed_groups and event.chat_id not in allowed_groups:
        return

    text = event.text or ""
    target = None

    if text.startswith('@'):
        target = text.split()[0].replace('@', '').strip().lower()
    elif event.is_reply and (text.lower() == 'скам' or text.lower().startswith('скам')):
        reply_msg = await event.get_reply_message()
        if reply_msg and reply_msg.sender and getattr(reply_msg.sender, 'username', None):
            target = reply_msg.sender.username.lower()

    if target:
        try:
            user_entity = await client.get_entity(target)
            user_id_str = str(user_entity.id)
        except Exception:
            user_id_str = "Неизвестен"

        if target in scammers_db:
            scam_data = scammers_db[target]
            warning_text = (
                f"⚠️ **ВНИМАНИЕ! ЭТО СКАМЕР!**\n\n"
                f"👤 **Пользователь:** @{target}\n"
                f"🆔 **ID:** `{user_id_str}`\n"
                f"❌ **Статус:** НАЙДЕН В БАЗЕ СКАМА\n"
                f"📝 **Причина:** {scam_data.get('reason', 'Не указано')}"
            )
            await event.reply(warning_text)
        else:
            await event.reply(
                f"✅ **ПРОВЕРКА ПРОЙДЕНА**\n\n"
                f"👤 **Пользователь:** @{target}\n"
                f"🆔 **ID:** `{user_id_str}`\n"
                f"ℹ️ **Статус:** В базе скама отсутствует."
            )

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
    await web_server()
    await client.start()
    print("Юзербот успешно запущен :)")
    await client.run_until_disconnected()

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())