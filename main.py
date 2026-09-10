import os
import asyncio
from aiogram import Bot, Dispatcher


async def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN is not set")

    bot = Bot(token=token)
    dp = Dispatcher()

    print("BOT STARTED", flush=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
