from telethon import TelegramClient  
API_ID = 39070752  
API_HASH = "a7f4346ee8e737e2c176d557a1e8df32"  
client = TelegramClient('userbot', API_ID, API_HASH)  
async def main(): print("OK")  
with client: client.loop.run_until_complete(main()) 
