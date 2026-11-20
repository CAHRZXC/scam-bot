@dp.message(F.document)
async def handle_db_file(message: types.Message):
    if message.from_user.id != ADMIN_ID:
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