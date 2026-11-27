# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""Rich media blocks: photo, video, audio, document, slideshow and collage.

A slideshow references media supplied in ``InputRichMessage.media``. Photo uses
``tg://photo?id=``, video and animation both use the ``<video>`` tag with
``tg://video?id=``, document uses ``<tg-document>`` with ``tg://document?id=``,
and audio uses ``tg://audio?id=``. Proof posts use that single rich path, so no
plain media upload runs alongside it. The id shape follows Kurigram's
``InputRichMessageMedia.id`` contract: 1-64 characters of ``A-Za-z0-9_-``.
"""

from __future__ import annotations

import re

from tcbot.modules.helper.rich.style import esc

_MEDIA_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_KINDS = frozenset({"photo", "video", "audio", "document", "animation"})


def photo(url: str, *, caption: str | None = None, credit: object | None = None) -> str:
    """Render a photo block, optionally with a captioned figure."""
    return _media("img", url, caption=caption, credit=credit, self_closing=True)


def video(url: str, *, caption: str | None = None, credit: object | None = None) -> str:
    """Render a video block, optionally with a captioned figure."""
    return _media("video", url, caption=caption, credit=credit)


def audio(url: str, *, caption: str | None = None, credit: object | None = None) -> str:
    """Render an audio block, optionally with a captioned figure."""
    return _media("audio", url, caption=caption, credit=credit)


def document(
    url: str, *, caption: str | None = None, credit: object | None = None
) -> str:
    """Render a general-file block, optionally with a captioned figure."""
    return _media("tg-document", url, caption=caption, credit=credit)


def slideshow(
    media: list[tuple[str, str]],
    *,
    caption: str | None = None,
    credit: object | None = None,
) -> str:
    """Render an ordered slideshow of media embedded in the rich message.

    ``media`` holds ``(id, kind)`` pairs; the id matches an attached
    ``InputRichMessageMedia`` and the kind is its Kurigram media type. The
    caption and its credit are direct children of the slideshow.
    """
    body = "".join(_embedded(media_id, kind) for media_id, kind in media)
    return f"<tg-slideshow>{body}{_caption(caption, credit)}</tg-slideshow>"


def _embedded(media_id: str, kind: str) -> str:
    """Render one slideshow item referencing an attached media object."""
    if not _MEDIA_ID_RE.fullmatch(media_id):
        raise ValueError("Rich media id must be 1-64 chars of A-Za-z0-9_-")
    if kind not in _KINDS:
        raise ValueError(f"Unsupported rich media kind: {kind}")
    if kind == "photo":
        return f'<img src="tg://photo?id={media_id}"/>'
    if kind in ("video", "animation"):
        # * Bot API maps animation to the video tag; there is no tg://animation.
        return f'<video src="tg://video?id={media_id}"></video>'
    if kind == "audio":
        return f'<audio src="tg://audio?id={media_id}"></audio>'
    return f'<tg-document src="tg://document?id={media_id}"></tg-document>'


def collage(
    urls: list[str], *, caption: str | None = None, credit: object | None = None
) -> str:
    """Render a media collage with an optional caption and credit."""
    body = "".join(_media("img", url, self_closing=True) for url in urls)
    return f"<tg-collage>{body}{_caption(caption, credit)}</tg-collage>"


def _caption(caption: str | None, credit: object | None = None) -> str:
    if not caption and credit is None:
        return ""
    cite = f"<cite>{esc(credit)}</cite>" if credit else ""
    label = esc(caption) if caption else ""
    return f"<figcaption>{label}{cite}</figcaption>"


def _media(
    tag: str,
    url: str,
    *,
    caption: str | None = None,
    credit: object | None = None,
    self_closing: bool = False,
) -> str:
    src = esc(url)
    caption_markup = _caption(caption, credit)
    media = f'<img src="{src}"/>' if self_closing else f'<{tag} src="{src}"></{tag}>'
    # * A standalone captioned media block is a figure; a bare figcaption
    # * belongs only inside a collage or slideshow.
    return f"<figure>{media}{caption_markup}</figure>" if caption_markup else media


__all__ = ["audio", "collage", "document", "photo", "slideshow", "video"]
