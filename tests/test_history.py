import json

from notetaker import history

RECORD = {
    "id": "testrec",
    "ts": "2026-11-26 12:00:00",
    "lang": "hi",
    "engine": "int4",
    "duration_s": 12.0,
    "turn_count": 2,
    "preview": "कुछ अणुओं में",
    "turns": [
        {"start": 0.7, "end": 8.3, "speaker": 0, "text": "कुछ अणुओं में अस्थिर केंद्रक होता है"},
        {"start": 10.8, "end": 22.8, "speaker": 1, "text": "ग्रीनलैंड को बहुत कम जगह बसाया गया था"},
    ],
}


def test_save_list_get_roundtrip(tmp_path):
    history.save(dict(RECORD), None, base=tmp_path)
    rows = history.listing(base=tmp_path)
    assert len(rows) == 1
    assert rows[0]["id"] == "testrec"
    assert rows[0]["turn_count"] == 2
    full = history.get("testrec", base=tmp_path)
    assert full["turns"][1]["speaker"] == 1
    assert history.get("nope", base=tmp_path) is None


def test_md_and_txt_contain_turns():
    md = history.as_md(RECORD)
    txt = history.as_txt(RECORD)
    assert "**speaker_00**" in md and "कुछ अणुओं" in md
    assert "speaker_01" in txt and "ग्रीनलैंड" in txt


def test_pdf_is_valid_and_embeds_font():
    pdf = history.as_pdf(RECORD)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 5000  # font subset embedded, not an empty shell
    assert b"NotoSansDevanagari" in pdf or b"NotoDev" in pdf


def test_listing_empty_dir(tmp_path):
    assert history.listing(base=tmp_path / "missing") == []
