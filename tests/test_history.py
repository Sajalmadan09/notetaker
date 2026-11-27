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
    assert "**Speaker 1**" in md and "कुछ अणुओं" in md
    assert "Speaker 2" in txt and "ग्रीनलैंड" in txt


def test_pdf_is_valid_and_embeds_font():
    pdf = history.as_pdf(RECORD)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 5000  # font subset embedded, not an empty shell
    assert b"NotoSansDevanagari" in pdf or b"NotoDev" in pdf


def test_listing_empty_dir(tmp_path):
    assert history.listing(base=tmp_path / "missing") == []


def test_listing_is_newest_first_not_by_id(tmp_path):
    history.save({**RECORD, "id": "aaa", "ts": "2026-11-27 09:00:00"}, None, base=tmp_path)
    history.save({**RECORD, "id": "zzz", "ts": "2026-11-26 09:00:00"}, None, base=tmp_path)
    assert [r["id"] for r in history.listing(base=tmp_path)] == ["aaa", "zzz"]


def test_update_names_title_flow_into_exports(tmp_path):
    history.save(dict(RECORD), None, base=tmp_path)
    rec = history.update("testrec", title="Standup", names={"1": "Priya"}, base=tmp_path)
    assert rec["names"] == {"1": "Priya"}
    md = history.as_md(rec)
    assert md.startswith("# Standup") and "**Priya**" in md and "**Speaker 1**" in md
    rec = history.update("testrec", names={"1": " "}, base=tmp_path)  # blank clears
    assert rec["names"] == {} and rec["title"] == "Standup"
    assert history.update("nope", title="x", base=tmp_path) is None


def test_delete_removes_files_and_rejects_traversal(tmp_path):
    wav = tmp_path / "src.wav"
    wav.write_bytes(b"RIFF")
    history.save(dict(RECORD), wav, base=tmp_path)
    assert history.delete("testrec", base=tmp_path)
    assert list(tmp_path.iterdir()) == []
    assert not history.delete("testrec", base=tmp_path)
    assert history.get("../etc/passwd", base=tmp_path) is None
