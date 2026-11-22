# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Rich media blocks: photo, video, slideshow, and collage.

Proof media uses a slideshow so a group of related images stays together in
one ordered, expandable block.
"""

from __future__ import annotations

from tcbot.modules.helper.messages.rich_style import esc


def photo(url: str, *, caption: str | None = None) -> str:
    """Render a photo block, optionally with a caption."""
    return _media("img", url, caption=caption, self_closing=True)


def video(url: str, *, caption: str | None = None) -> str:
    """Render a video block, optionally with a caption."""
    return _media("video", url, caption=caption)


def slideshow(urls: list[str], *, caption: str | None = None) -> str:
    """Render an ordered media slideshow."""
    body = "".join(_media("img", url, self_closing=True) for url in urls)
    return f"<tg-slideshow>{body}{_caption(caption)}</tg-slideshow>"


def proof_slideshow(urls: list[str], *, caption: str | None = None) -> str:
    """Render proof media as a slideshow, the canonical proof layout."""
    return slideshow(urls, caption=caption)


def collage(urls: list[str], *, caption: str | None = None) -> str:
    """Render a media collage."""
    body = "".join(_media("img", url, self_closing=True) for url in urls)
    return f"<tg-collage>{body}{_caption(caption)}</tg-collage>"


def _caption(caption: str | None) -> str:
    return f"<figcaption>{esc(caption)}</figcaption>" if caption else ""


def _media(
    tag: str, url: str, *, caption: str | None = None, self_closing: bool = False
) -> str:
    src = esc(url)
    caption_markup = _caption(caption)
    if self_closing:
        return f'<img src="{src}"/>{caption_markup}'
    return f'<{tag} src="{src}"></{tag}>{caption_markup}'


__all__ = ["collage", "photo", "proof_slideshow", "slideshow", "video"]
