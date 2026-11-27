"""Persistent recording history (local disk) + Markdown / TXT / PDF export.

PDF uses fpdf2 + uharfbuzz with a bundled Noto Sans Devanagari (OFL) so Hindi
matras/conjuncts shape correctly instead of rendering as broken glyph runs.
"""
from __future__ import annotations

import json
import re
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
    keys = ("id", "ts", "title", "lang", "engine", "duration_s", "turn_count", "preview",
            "audio", "source", "verdict")
    out = [{k: r.get(k) for k in keys}
           for r in (json.loads(p.read_text()) for p in base.glob("*.json"))]
    return sorted(out, key=lambda r: r["ts"] or "", reverse=True)  # ids are random; ts is chronological


def _path(rid: str, base: Path | None, ext: str) -> Path | None:
    if not re.fullmatch(r"[\w-]+", rid):
        return None
    return (base or HISTORY_DIR) / f"{rid}.{ext}"


def get(rid: str, base: Path | None = None) -> dict | None:
    path = _path(rid, base, "json")
    return json.loads(path.read_text()) if path and path.exists() else None


def update(rid: str, title: str | None = None, names: dict | None = None,
           summary: dict | None = None, base: Path | None = None) -> dict | None:
    """Set title, speaker names ({"0": "Priya"}; blank clears) and/or the AI summary."""
    record = get(rid, base)
    if record is None:
        return None
    if summary is not None:
        record["summary"] = summary
        if not record.get("title") and summary.get("title"):
            record["title"] = summary["title"][:120]
    if title is not None:
        record["title"] = title.strip()[:120]
    if names is not None:
        merged = {**record.get("names", {}), **{str(int(k)): str(v).strip()[:60] for k, v in names.items()}}
        record["names"] = {k: v for k, v in merged.items() if v}
    _path(rid, base, "json").write_text(json.dumps(record, ensure_ascii=False, indent=2))
    return record


def delete(rid: str, base: Path | None = None) -> bool:
    found = False
    for ext in ("json", "wav"):
        path = _path(rid, base, ext)
        if path and path.exists():
            path.unlink()
            found = True
    return found


def speaker(record: dict, spk: int) -> str:
    return record.get("names", {}).get(str(spk)) or f"Speaker {spk + 1}"  # matches the app UI


def _title(record: dict) -> str:
    return record.get("title") or f"Notetaker — {record.get('ts', '')}"


def as_md(record: dict) -> str:
    lines = [f"# {_title(record)}",
             f"language: {record.get('lang')} · duration: {record.get('duration_s')}s", ""]
    if s := record.get("summary"):
        lines += ["## Summary", "", s.get("overview", ""), ""]
        if s.get("action_items"):
            lines += ["## Action items", ""] + [
                f"- [{'x' if a.get('done') else ' '}] {a['text']}" + (f" — {a['owner']}" if a.get("owner") else "")
                for a in s["action_items"]] + [""]
        if s.get("decisions"):
            lines += ["## Decisions", ""] + [f"- {d}" for d in s["decisions"]] + [""]
        lines += ["## Transcript", ""]
    for t in record.get("turns", []):
        lines.append(f"**{speaker(record, t['speaker'])}** [{t['start']:.1f}-{t['end']:.1f}]: {t['text']}")
        lines.append("")
    return "\n".join(lines)


def as_txt(record: dict) -> str:
    lines = [_title(record),
             f"language: {record.get('lang')} · duration: {record.get('duration_s')}s", ""]
    for t in record.get("turns", []):
        lines.append(f"{speaker(record, t['speaker'])} [{t['start']:.1f}-{t['end']:.1f}]")
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
    pdf.cell(text=record.get("title") or "Notetaker — meeting notes", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("NotoDev", size=10)
    pdf.set_text_color(110, 106, 102)
    pdf.cell(text=f"{record.get('ts', '')} · language {record.get('lang')} · "
                  f"{record.get('duration_s')}s · {record.get('turn_count')} turns",
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(4)
    for t in record.get("turns", []):
        pdf.set_font("NotoDev", size=10)
        pdf.set_text_color(180, 85, 45)
        pdf.cell(text=f"{speaker(record, t['speaker'])}  [{t['start']:.1f}s – {t['end']:.1f}s]",
                 new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("NotoDev", size=12)
        pdf.set_text_color(20, 19, 18)
        pdf.multi_cell(w=0, h=7, text=t["text"], new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(3)
    return bytes(pdf.output())
