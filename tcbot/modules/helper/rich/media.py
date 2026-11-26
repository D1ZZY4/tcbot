# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Rich media blocks: photo, video, slideshow, and collage.

A slideshow references media supplied in ``InputRichMessage.media`` through
``tg://photo|video|document|audio?id=`` links. Proof posts use that single rich
path, so no plain media upload runs alongside it.
"""

from __future__ import annotations

from tcbot.modules.helper.rich.style import esc


def photo(url: str, *, caption: str | None = None) -> str:
    """Render a photo block, optionally with a caption."""
    return _media("img", url, caption=caption, self_closing=True)


def video(url: str, *, caption: str | None = None) -> str:
    """Render a video block, optionally with a caption."""
    return _media("video", url, caption=caption)


def slideshow(media: list[tuple[str, str]], *, caption: str | None = None) -> str:
    """Render an ordered slideshow of media embedded in the rich message.

    ``media`` holds ``(id, kind)`` pairs, where the id matches an
    ``InputRichMessageMedia.id`` and the kind is the Kurigram media type. The
    caption is a direct child of the slideshow, which is the only valid
    location for a bare figcaption.
    """
    body = "".join(_embedded(media_id, kind) for media_id, kind in media)
    return f"<tg-slideshow>{body}{_caption(caption)}</tg-slideshow>"


def _embedded(media_id: str, kind: str) -> str:
    """Render one slideshow item referencing an attached media object."""
    safe_id = esc(media_id)
    if kind == "photo":
        return f'<img src="tg://photo?id={safe_id}"/>'
    if kind == "video":
        return f'<video src="tg://video?id={safe_id}"></video>'
    if kind == "audio":
        return f'<audio src="tg://audio?id={safe_id}"></audio>'
    return f'<img src="tg://document?id={safe_id}"/>'


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
    media = f'<img src="{src}"/>' if self_closing else f'<{tag} src="{src}"></{tag}>'
    # * The Bot API documents a standalone captioned image or video as a
    # * figure; a bare figcaption is only valid inside a collage or slideshow.
    return f"<figure>{media}{caption_markup}</figure>" if caption_markup else media


__all__ = ["collage", "photo", "slideshow", "video"]
