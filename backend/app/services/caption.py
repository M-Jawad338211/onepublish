"""Caption builder (FR-28, FR-32–34, FR-25).

Template: prefix / title / description / hashtags / suffix, separated by blank lines.
TikTok counts the 2200 limit in UTF-16 code units, so all length math uses that.
"""

import re
import unicodedata
from dataclasses import dataclass, field

TIKTOK_CAPTION_MAX = 2200

_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_MENTION_RE = re.compile(r"(?<![\w@])@[\w.\-]+")
_HASHTAG_RE = re.compile(r"(?<![\w#])#(\w+)", re.UNICODE)
_SPACES_RE = re.compile(r"[ \t]+")
_BLANKS_RE = re.compile(r"\n{3,}")


@dataclass
class CaptionOptions:
    include_title: bool = True
    include_description: bool = True
    include_tags: bool = True
    prefix: str = ""
    suffix: str = ""
    extra_tags: list[str] = field(default_factory=list)
    strip_tags: list[str] = field(default_factory=lambda: ["shorts"])
    max_len: int | None = None


def utf16_len(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def to_hashtag(tag: str) -> str:
    """'Home Cooking!' -> 'HomeCooking'. Keeps letters, digits and underscore only."""
    tag = unicodedata.normalize("NFC", tag.strip().lstrip("#"))
    return "".join(ch for ch in tag if ch.isalnum() or ch == "_")


def _clean_text(text: str, strip: set[str]) -> str:
    text = _URL_RE.sub("", text)
    text = _MENTION_RE.sub("", text)

    def drop_tag(m: re.Match[str]) -> str:
        return "" if m.group(1).lower() in strip else m.group(0)

    text = _HASHTAG_RE.sub(drop_tag, text)
    lines = [_SPACES_RE.sub(" ", line).strip() for line in text.splitlines()]
    return _BLANKS_RE.sub("\n\n", "\n".join(lines)).strip()


def _truncate(text: str, limit: int, ellipsis: str = "…") -> str:
    """Cut to at most `limit` UTF-16 units, at a word boundary when one is close."""
    if utf16_len(text) <= limit:
        return text
    budget = limit - utf16_len(ellipsis)
    if budget <= 0:
        return ""
    out = []
    used = 0
    for ch in text:
        n = utf16_len(ch)
        if used + n > budget:
            break
        out.append(ch)
        used += n
    cut = "".join(out)
    space = max(cut.rfind(" "), cut.rfind("\n"))
    if space >= len(cut) * 0.6:
        cut = cut[:space]
    return cut.rstrip() + ellipsis


def build_caption(
    title: str, description: str, tags: list[str], opts: CaptionOptions | None = None
) -> str:
    opts = opts or CaptionOptions()
    strip = {t.lower().lstrip("#") for t in opts.strip_tags}
    limit = min(opts.max_len or TIKTOK_CAPTION_MAX, TIKTOK_CAPTION_MAX)

    title_txt = _clean_text(title, strip) if opts.include_title else ""
    desc_txt = _clean_text(description, strip) if opts.include_description else ""

    present = {m.lower() for m in _HASHTAG_RE.findall(f"{title_txt}\n{desc_txt}")}
    hashtags: list[str] = []
    source_tags = (tags if opts.include_tags else []) + list(opts.extra_tags)
    for raw in source_tags:
        tag = to_hashtag(raw)
        if not tag or tag.lower() in strip or tag.lower() in present:
            continue
        present.add(tag.lower())
        hashtags.append(f"#{tag}")
    tags_txt = " ".join(hashtags)

    def assemble(desc: str) -> str:
        parts = [opts.prefix.strip(), title_txt, desc, tags_txt, opts.suffix.strip()]
        return "\n\n".join(p for p in parts if p)

    caption = assemble(desc_txt)
    if utf16_len(caption) <= limit:
        return caption

    # Shorten the description first so the title and hashtags survive.
    room = limit - utf16_len(assemble(""))
    if desc_txt and room > 0:
        sep = 2  # the "\n\n" the description adds back
        caption = assemble(_truncate(desc_txt, room - sep))
        if utf16_len(caption) <= limit:
            return caption
    return _truncate(assemble(""), limit)
