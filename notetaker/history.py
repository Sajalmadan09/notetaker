"""Persistent recording history (local disk) + Markdown / TXT / PDF export.

PDF uses fpdf2 + uharfbuzz with a bundled Noto Sans Devanagari (OFL) so Hindi
matras/conjuncts shape correctly instead of rendering as broken glyph runs.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import paths

HISTORY_DIR = paths.DATA / "history"
FONT = paths.BUNDLE / "notetaker" / "assets" / "NotoSansDevanagari-Regular.ttf"
FONT_LATIN = paths.BUNDLE / "notetaker" / "assets" / "NotoSans-Regular.ttf"


def save(record: dict, audio_src: Path | None, base: Path | None = None) -> dict:
    base = base or HISTORY_DIR
    base.mkdir(parents=True, exist_ok=True)
    rid = record["id"]
    if audio_src is not None and audio_src.exists():
        audio_src.rename(base / f"{rid}.wav")
        record["audio"] = f"{rid}.wav"
    (base / f"{rid}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2))
    return record


def listing(base: Path | None = None) -> list[dict]:
    base = base or HISTORY_DIR
    if not base.exists():
        return []
    keys = ("id", "ts", "lang", "engine", "duration_s", "turn_count", "preview",
            "audio", "source", "verdict")
    out = []
    for path in sorted(base.glob("*.json"), reverse=True):
        record = json.loads(path.read_text())
        out.append({k: record.get(k) for k in keys})
    return out


def get(rid: str, base: Path | None = None) -> dict | None:
    path = (base or HISTORY_DIR) / f"{rid}.json"
    return json.loads(path.read_text()) if path.exists() else None


def as_md(record: dict) -> str:
    lines = [f"# Notetaker — {record.get('ts', '')}",
             f"language: {record.get('lang')} · duration: {record.get('duration_s')}s", ""]
    for t in record.get("turns", []):
        lines.append(f"**speaker_{t['speaker']:02d}** [{t['start']:.1f}-{t['end']:.1f}]: {t['text']}")
        lines.append("")
    return "\n".join(lines)


def as_txt(record: dict) -> str:
    lines = [f"Notetaker — {record.get('ts', '')}",
             f"language: {record.get('lang')} · duration: {record.get('duration_s')}s", ""]
    for t in record.get("turns", []):
        lines.append(f"speaker_{t['speaker']:02d} [{t['start']:.1f}-{t['end']:.1f}]")
        lines.append(t["text"])
        lines.append("")
    return "\n".join(lines)


def as_pdf(record: dict) -> bytes:
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos

    pdf = FPDF(format="A4")
    pdf.add_font("NotoDev", "", str(FONT))
    # Devanagari font has no Latin glyphs; fall back per-glyph for labels/titles.
    pdf.add_font("NotoLatin", "", str(FONT_LATIN))
    pdf.set_fallback_fonts(["NotoLatin"])
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    pdf.set_font("NotoDev", size=16)
    pdf.cell(text="Notetaker — meeting notes", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("NotoDev", size=10)
    pdf.set_text_color(110, 106, 102)
    pdf.cell(text=f"{record.get('ts', '')} · language {record.get('lang')} · "
                  f"{record.get('duration_s')}s · {record.get('turn_count')} turns",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(4)
    for t in record.get("turns", []):
        pdf.set_font("NotoDev", size=10)
        pdf.set_text_color(180, 85, 45)
        pdf.cell(text=f"speaker_{t['speaker']:02d}  [{t['start']:.1f}s – {t['end']:.1f}s]",
                 new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("NotoDev", size=12)
        pdf.set_text_color(20, 19, 18)
        pdf.multi_cell(w=0, h=7, text=t["text"], new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(3)
    return bytes(pdf.output())
