import os
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from aiohttp import ClientSession
from discord import Color, Embed, Message
from discord.ext.commands import Bot

GITEA_HOST = "10.77.0.20"
GITEA_BASE_URL = f"http://{GITEA_HOST}"
GITEA_API_BASE = f"{GITEA_BASE_URL}/api/v1"
GITEA_URL_PATTERN = re.compile(r"http://10\.77\.0\.20/[-\w./()?%&=!~#]*")

COLOR_GITEA = Color(0x609926)
COLOR_ISSUE_OPEN = Color(0x28A745)
COLOR_ISSUE_CLOSED = Color(0xCB2431)
COLOR_PR_MERGED = Color(0x6F42C1)
COLOR_COMMIT = Color(0x0366D6)
COLOR_USER = Color(0x586069)


class GiteaResourceType(Enum):
    REPO = auto()
    ISSUE = auto()
    PULL_REQUEST = auto()
    COMMIT = auto()
    USER = auto()
    UNKNOWN = auto()


@dataclass
class GiteaResource:
    resource_type: GiteaResourceType
    owner: str
    repo: Optional[str] = None
    number: Optional[int] = None
    sha: Optional[str] = None
    url: str = ""


def parse_gitea_url(url: str) -> GiteaResource:
    parsed = urlparse(url)
    parts = PurePosixPath(parsed.path).parts

    # parts[0] is always "/"
    if len(parts) < 2:
        return GiteaResource(GiteaResourceType.UNKNOWN, owner="", url=url)

    owner = parts[1]

    # /{owner}
    if len(parts) == 2:
        return GiteaResource(GiteaResourceType.USER, owner=owner, url=url)

    repo = parts[2]

    # /{owner}/{repo}
    if len(parts) == 3:
        return GiteaResource(GiteaResourceType.REPO, owner=owner, repo=repo, url=url)

    # /{owner}/{repo}/issues/{n}
    if len(parts) >= 5 and parts[3] == "issues":
        try:
            number = int(parts[4])
        except ValueError:
            return GiteaResource(GiteaResourceType.UNKNOWN, owner=owner, url=url)
        return GiteaResource(
            GiteaResourceType.ISSUE,
            owner=owner,
            repo=repo,
            number=number,
            url=url,
        )

    # /{owner}/{repo}/pulls/{n}
    if len(parts) >= 5 and parts[3] == "pulls":
        try:
            number = int(parts[4])
        except ValueError:
            return GiteaResource(GiteaResourceType.UNKNOWN, owner=owner, url=url)
        return GiteaResource(
            GiteaResourceType.PULL_REQUEST,
            owner=owner,
            repo=repo,
            number=number,
            url=url,
        )

    # /{owner}/{repo}/commit/{sha}
    if len(parts) >= 5 and parts[3] == "commit":
        return GiteaResource(
            GiteaResourceType.COMMIT,
            owner=owner,
            repo=repo,
            sha=parts[4],
            url=url,
        )

    return GiteaResource(GiteaResourceType.UNKNOWN, owner=owner, url=url)


def _parse_datetime(value: str) -> datetime:
    # Python 3.9 の fromisoformat は "Z" を扱えないため置換する
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class GiteaClient:
    def __init__(self, token: str) -> None:
        self._token = token

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"token {self._token}"}

    async def _get(self, path: str) -> Optional[Dict[str, Any]]:
        url = f"{GITEA_API_BASE}{path}"
        async with ClientSession(headers=self._headers()) as session:
            try:
                async with session.get(url) as response:
                    if response.status != 200:
                        return None
                    data: Dict[str, Any] = await response.json()
                    return data
            except Exception:
                return None

    async def get_repo(self, owner: str, repo: str) -> Optional[Dict[str, Any]]:
        return await self._get(f"/repos/{owner}/{repo}")

    async def get_issue(
        self, owner: str, repo: str, number: int
    ) -> Optional[Dict[str, Any]]:
        return await self._get(f"/repos/{owner}/{repo}/issues/{number}")

    async def get_pull(
        self, owner: str, repo: str, number: int
    ) -> Optional[Dict[str, Any]]:
        return await self._get(f"/repos/{owner}/{repo}/pulls/{number}")

    async def get_commit(
        self, owner: str, repo: str, sha: str
    ) -> Optional[Dict[str, Any]]:
        return await self._get(f"/repos/{owner}/{repo}/git/commits/{sha}")

    async def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        return await self._get(f"/users/{username}")


def _build_repo_embed(data: Dict[str, Any], url: str) -> Embed:
    full_name = data.get("full_name", "")
    description = data.get("description", "") or ""
    embed = Embed(title=full_name, url=url, description=description, color=COLOR_GITEA)
    embed.add_field(name="Stars", value=str(data.get("stars_count", 0)), inline=True)
    embed.add_field(name="Forks", value=str(data.get("forks_count", 0)), inline=True)
    embed.add_field(
        name="Open Issues",
        value=str(data.get("open_issues_count", 0)),
        inline=True,
    )
    language = data.get("language", "")
    if language:
        embed.add_field(name="Language", value=language, inline=True)
    owner_data = data.get("owner", {})
    if owner_data:
        embed.set_author(
            name=owner_data.get("login", ""),
            icon_url=owner_data.get("avatar_url", ""),
        )
    embed.set_footer(text=full_name)
    if data.get("created_at"):
        embed.timestamp = _parse_datetime(data["created_at"])
    return embed


def _state_emoji(state: str) -> str:
    if state == "open":
        return "\U0001f7e2"  # green circle
    if state == "closed":
        return "\U0001f534"  # red circle
    return ""


def _build_issue_embed(data: Dict[str, Any], resource: GiteaResource) -> Embed:
    state = data.get("state", "open")
    color = COLOR_ISSUE_OPEN if state == "open" else COLOR_ISSUE_CLOSED
    title = f"#{data.get('number', '')} {data.get('title', '')}"
    body = data.get("body", "") or ""
    description = body[:200] + ("..." if len(body) > 200 else "")

    embed = Embed(title=title, url=resource.url, description=description, color=color)
    embed.add_field(
        name="State", value=f"{_state_emoji(state)} {state}", inline=True
    )

    labels: List[Dict[str, Any]] = data.get("labels", []) or []
    if labels:
        label_names = ", ".join(lb.get("name", "") for lb in labels)
        embed.add_field(name="Labels", value=label_names, inline=True)

    embed.add_field(
        name="Comments", value=str(data.get("comments", 0)), inline=True
    )

    user = data.get("user", {})
    if user:
        embed.set_author(
            name=user.get("login", ""), icon_url=user.get("avatar_url", "")
        )
    embed.set_footer(text=f"{resource.owner}/{resource.repo}")
    if data.get("created_at"):
        embed.timestamp = _parse_datetime(data["created_at"])
    return embed


def _pr_state_label(data: Dict[str, Any]) -> str:
    if data.get("merged"):
        return "merged"
    return str(data.get("state", "open"))


def _pr_color(data: Dict[str, Any]) -> Color:
    if data.get("merged"):
        return COLOR_PR_MERGED
    state = data.get("state", "open")
    if state == "open":
        return COLOR_ISSUE_OPEN
    return COLOR_ISSUE_CLOSED


def _build_pull_embed(data: Dict[str, Any], resource: GiteaResource) -> Embed:
    state_label = _pr_state_label(data)
    color = _pr_color(data)
    title = f"#{data.get('number', '')} {data.get('title', '')}"
    body = data.get("body", "") or ""
    description = body[:200] + ("..." if len(body) > 200 else "")

    embed = Embed(title=title, url=resource.url, description=description, color=color)
    embed.add_field(
        name="State",
        value=f"{_state_emoji(state_label)} {state_label}",
        inline=True,
    )

    labels: List[Dict[str, Any]] = data.get("labels", []) or []
    if labels:
        label_names = ", ".join(lb.get("name", "") for lb in labels)
        embed.add_field(name="Labels", value=label_names, inline=True)

    user = data.get("user", {})
    if user:
        embed.set_author(
            name=user.get("login", ""), icon_url=user.get("avatar_url", "")
        )
    embed.set_footer(text=f"{resource.owner}/{resource.repo}")
    if data.get("created_at"):
        embed.timestamp = _parse_datetime(data["created_at"])
    return embed


def _build_commit_embed(data: Dict[str, Any], resource: GiteaResource) -> Embed:
    sha = data.get("sha", "") or ""
    short_sha = sha[:7]
    commit_info = data.get("commit", {}) or {}
    message = commit_info.get("message", "") or ""
    lines = message.split("\n", 1)
    first_line = lines[0]
    rest = lines[1].strip() if len(lines) > 1 else ""

    title = f"`{short_sha}` {first_line}"
    embed = Embed(
        title=title, url=resource.url, description=rest[:200], color=COLOR_COMMIT
    )

    author_info = commit_info.get("author", {}) or {}
    committer_name = author_info.get("name", "")
    if committer_name:
        embed.set_author(name=committer_name)

    embed.set_footer(text=f"{resource.owner}/{resource.repo}")
    if author_info.get("date"):
        embed.timestamp = _parse_datetime(author_info["date"])
    return embed


def _build_user_embed(data: Dict[str, Any], url: str) -> Embed:
    login = data.get("login", "")
    bio = data.get("description", "") or data.get("bio", "") or ""
    embed = Embed(title=login, url=url, description=bio, color=COLOR_USER)
    avatar = data.get("avatar_url", "")
    if avatar:
        embed.set_thumbnail(url=avatar)
    embed.set_footer(text="Gitea")
    if data.get("created"):
        embed.timestamp = _parse_datetime(data["created"])
    return embed


async def on_message(message: Message) -> None:
    if message.author.bot:
        return

    urls = GITEA_URL_PATTERN.findall(message.content)
    if not urls:
        return

    token = os.environ.get("GITEA_TOKEN", "")
    client = GiteaClient(token)

    for url in urls:
        resource = parse_gitea_url(url)

        if resource.resource_type == GiteaResourceType.UNKNOWN:
            continue

        embed: Optional[Embed] = None

        try:
            if resource.resource_type == GiteaResourceType.REPO:
                assert resource.repo is not None
                data = await client.get_repo(resource.owner, resource.repo)
                if data:
                    embed = _build_repo_embed(data, url)

            elif resource.resource_type == GiteaResourceType.ISSUE:
                assert resource.repo is not None
                assert resource.number is not None
                data = await client.get_issue(
                    resource.owner, resource.repo, resource.number
                )
                if data:
                    embed = _build_issue_embed(data, resource)

            elif resource.resource_type == GiteaResourceType.PULL_REQUEST:
                assert resource.repo is not None
                assert resource.number is not None
                data = await client.get_pull(
                    resource.owner, resource.repo, resource.number
                )
                if data:
                    embed = _build_pull_embed(data, resource)

            elif resource.resource_type == GiteaResourceType.COMMIT:
                assert resource.repo is not None
                assert resource.sha is not None
                data = await client.get_commit(
                    resource.owner, resource.repo, resource.sha
                )
                if data:
                    embed = _build_commit_embed(data, resource)

            elif resource.resource_type == GiteaResourceType.USER:
                data = await client.get_user(resource.owner)
                if data:
                    embed = _build_user_embed(data, url)

        except Exception:
            continue

        if embed is not None:
            await message.channel.send(embed=embed)


async def setup(bot: Bot) -> None:
    bot.add_listener(on_message)
