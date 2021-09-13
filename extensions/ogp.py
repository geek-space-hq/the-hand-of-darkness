import asyncio
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import bs4
import requests
from aiohttp import ClientSession
from discord import Embed, File, Message
from discord.ext.commands import Bot

GSNET_URL_PATTERN = re.compile(r"http://10\.\d{,3}\.\d{,3}\.\d{,3}[-\w./()?%&=!~#]*")
BOT_HEDERS = {"User-Agent": "6ZeH44Gu5omL44GM5p2l44Gf44KI44CcCg=="}


def save_file(url: str, file_path: Path) -> None:
    response = requests.get(url, headers=BOT_HEDERS)
    response.raise_for_status()
    with open(file_path, "wb") as f:
        f.write(response.content)


def get_png_favicon_file(favicon_url: str, directory: Path) -> File:
    favicon_path = Path(directory) / "favicon.ico"
    save_file(favicon_url, favicon_path)
    res = subprocess.run(
        ["./extract-ico.sh"],
        input=bytes(favicon_path),
        capture_output=True,
        check=True,
    )
    favicon_png_path = Path(res.stdout.decode().rstrip())
    return File(favicon_png_path, filename="favicon.png")


def get_ogp_file(image_url: str, directory: Path) -> File:
    file_name = Path(urlparse(image_url).path).name
    file_path = Path(directory) / file_name
    save_file(image_url, file_path)
    return File(file_path, filename=file_name)


@dataclass
class PageInfo:
    title: str
    url: str
    description: Optional[str]
    image_url: Optional[str]
    favicon_url: Optional[str] = None

    def to_embed(self) -> Embed:
        embed = Embed(
            title=self.title, url=self.url, description=self.description or ""
        )
        if self.image_url is None:
            parsed_url = urlparse(self.url)
            self.favicon_url = f"{parsed_url.scheme}://{parsed_url.netloc}/favicon.ico"

        return embed


@dataclass
class Page:
    url: str
    html: bytes

    def get_info(self) -> PageInfo:
        soup = bs4.BeautifulSoup(self.html, "lxml")

        if title_tag := soup.select_one(r"meta[property=og\:title]"):
            title = title_tag["content"]
        elif title_tag := soup.select_one("title"):
            title = title_tag.text
        else:
            title = self.url[8:]  # https:// を消す

        if description_tag := soup.select_one(r"meta[property=og\:description]"):
            description = description_tag["content"]
        else:
            description = None

        if image_tag := soup.select_one(r"meta[property=og\:image]"):
            image_url = image_tag["content"]
        else:
            image_url = None

        return PageInfo(title, self.url, description, image_url)


def get_gsnet_urls(string: str) -> list[str]:
    return GSNET_URL_PATTERN.findall(string)


async def get_page(url: str) -> Optional[Page]:
    async with ClientSession(headers=BOT_HEDERS) as session:
        try:
            async with session.get(url) as response:
                if response.status != 200:
                    return None
                return Page(url, await response.read())
        except:  # うまく取れないものは全て要らないので、握りつぶして殺す
            return None


async def on_message(message: Message) -> None:
    if len(gsnet_urls := get_gsnet_urls(message.content)) == 0:
        return
    all_pages = await asyncio.gather(*[get_page(url) for url in gsnet_urls])
    found_pages = filter(None, all_pages)
    page_infos = list(map(lambda p: p.get_info(), found_pages))
    page_embeds = list(map(lambda i: i.to_embed(), page_infos))

    for embed, info in zip(page_embeds, page_infos):
        temp_dir = tempfile.TemporaryDirectory()

        if info.image_url is not None:
            try:
                file = get_ogp_file(info.image_url, Path(temp_dir.name))
                embed.set_image(url=f"attachment://{file.filename}")
            except:
                file = None

        else:
            try:
                file = get_png_favicon_file(info.favicon_url, Path(temp_dir.name))
                embed.set_thumbnail(url=f"attachment://{file.filename}")
            except:
                file = None

        await message.channel.send(embed=embed, file=file)

        temp_dir.cleanup()


def setup(bot: Bot):
    bot.add_listener(on_message)
