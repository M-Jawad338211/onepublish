from app.services.caption import CaptionOptions, build_caption, to_hashtag, utf16_len


def test_template_order_and_hashtags():
    caption = build_caption("My title", "Line one\nLine two", ["home cooking", "pasta"])
    assert caption == "My title\n\nLine one\nLine two\n\n#homecooking #pasta"


def test_strips_links_mentions_and_shorts_tag():
    caption = build_caption(
        "Big news #shorts",
        "Watch https://example.com/x and www.foo.com, thanks @friend!\n#Shorts #cats",
        ["shorts", "cats", "dogs"],
    )
    assert "http" not in caption and "www." not in caption
    assert "@friend" not in caption
    assert "#shorts" not in caption.lower()
    # #cats already in the description, so the tag is not repeated
    assert caption.count("#cats") == 1
    assert caption.endswith("#dogs")


def test_email_is_not_treated_as_mention():
    assert "me@example.com" in build_caption("", "mail me@example.com", [])


def test_to_hashtag_drops_non_alphanumerics():
    assert to_hashtag("Rock 'n' Roll!") == "RocknRoll"
    assert to_hashtag("#café_time") == "café_time"
    assert to_hashtag("!!!") == ""


def test_mapping_overrides():
    opts = CaptionOptions(
        include_description=False,
        prefix="NEW:",
        suffix="Follow for more",
        extra_tags=["brand"],
    )
    caption = build_caption("Title", "desc", ["a"], opts)
    assert caption == "NEW:\n\nTitle\n\n#a #brand\n\nFollow for more"


def test_truncates_description_first_and_keeps_tags():
    long_desc = "word " * 1000
    caption = build_caption("Title", long_desc, ["keep"])
    assert utf16_len(caption) <= 2200
    assert caption.startswith("Title")
    assert caption.endswith("#keep")
    assert "…" in caption


def test_limit_counts_utf16_units():
    emoji = "😀" * 1500  # 2 UTF-16 units each
    caption = build_caption(emoji, "", [], CaptionOptions(max_len=100))
    assert utf16_len(caption) <= 100
    assert len(caption) < 100


def test_empty_inputs():
    assert build_caption("", "", []) == ""
