import asyncio

from app.bot import CopycatBot


async def main():
    bot = CopycatBot()
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
