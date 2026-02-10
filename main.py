import os

from discord import Intents
from discord.ext.commands import Bot, when_mentioned


BOT_EXTENSIONS = ["ogp", "gitea"]


class MyBot(Bot):
    def __init__(self) -> None:
        intents = Intents.default()
        intents.message_content = True
        super().__init__(command_prefix=when_mentioned, intents=intents)

    async def setup_hook(self) -> None:
        for extension in BOT_EXTENSIONS:
            await self.load_extension("extensions." + extension)

    async def on_ready(self) -> None:
        print(self.user.name)
        print(self.user.id, "\n")


if __name__ == "__main__":
    bot = MyBot()
    bot.run(os.environ["DISCORD_TOKEN"])
