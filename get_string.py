from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = 39070752
API_HASH = "a7f4346ee8e737e2c176d557a1e8df32"

client = TelegramClient(StringSession(), API_ID, API_HASH)


async def main():
  await client.start()
  print("\n--- СКОПИРУЙ СТРОКУ НИЖЕ ---")
  print(client.session.save())
  print("----------------------------\n")


with client:
  client.loop.run_until_complete(main())