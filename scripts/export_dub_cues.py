#!/usr/bin/env python3
"""Export speaker-labeled and clone-safe subtitle files from 07-dubbing/*.cues.json."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

KIND_ZH = {
    "intro": "出场简介",
    "dialogue": "口述",
    "inner": "心里",
    "narration": "旁白",
    "sms": "短信",
    "reaction": "反应",
}


def stamp_srt(ms: int) -> str:
    if ms < 0:
        ms = 0
    h, rest = divmod(ms, 3_600_000)
    m, rest = divmod(rest, 60_000)
    s, milli = divmod(rest, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{milli:03d}"


def stamp_ass(ms: int) -> str:
    if ms < 0:
        ms = 0
    h, rest = divmod(ms, 3_600_000)
    m, rest = divmod(rest, 60_000)
    s, milli = divmod(rest, 1000)
    cs = milli // 10
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def write_srt(path: Path, blocks: list[tuple[int, int, int, str]]) -> None:
    chunks: list[str] = []
    for i, (start, end, _, text) in enumerate(blocks, start=1):
        chunks.extend(
            [
                str(i),
                f"{stamp_srt(start)} --> {stamp_srt(end)}",
                text,
                "",
            ]
        )
    path.write_text("\n".join(chunks), encoding="utf-8")


def write_ass(path: Path, cues: list[dict], field: str) -> None:
    events = [
        "[Script Info]",
        f"Title: {path.stem}",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Default,PingFang SC,48,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,0,2,40,40,96,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for cue in cues:
        text = str(cue.get(field) or "").strip()
        if not text:
            continue
        actor = str(cue.get("speaker_id") or "unknown")
        events.append(
            "Dialogue: 0,{start},{end},Default,{actor},0,0,0,,{text}".format(
                start=stamp_ass(int(cue["start_ms"])),
                end=stamp_ass(int(cue["end_ms"])),
                actor=actor,
                text=text.replace("\n", "\\N"),
            )
        )
    path.write_text("\n".join(events) + "\n", encoding="utf-8")


def labeled_body(cue: dict, text: str, lang: str) -> str:
    sid = str(cue.get("speaker_id") or "unknown")
    display_key = "display_km" if lang == "km" else "display_zh"
    display = str(cue.get(display_key) or cue.get("display_zh") or sid)
    kind = KIND_ZH.get(str(cue.get("line_kind") or ""), str(cue.get("line_kind") or ""))
    return f"[{sid} / {display} / {kind}]\n{text}"


def export_lang(cues: list[dict], dest: Path, lang: str) -> list[Path]:
    text_key = f"text_{lang}"
    cap_key = f"caption_{lang}"
    spoken: list[tuple[int, int, int, str]] = []
    caption: list[tuple[int, int, int, str]] = []
    labeled: list[tuple[int, int, int, str]] = []
    for cue in cues:
        start, end, index = int(cue["start_ms"]), int(cue["end_ms"]), int(cue["index"])
        spoken_text = str(cue.get(text_key) or "").strip()
        cap_text = str(cue.get(cap_key) or "").strip()
        if not spoken_text:
            continue
        spoken.append((start, end, index, spoken_text))
        labeled.append((start, end, index, labeled_body(cue, spoken_text, lang)))
        caption.append((start, end, index, cap_text or spoken_text))

    written: list[Path] = []
    if not spoken:
        return written

    p_spoken = dest / f"ep01.{lang}.srt"
    p_labeled = dest / f"ep01.{lang}.labeled.srt"
    p_caption = dest / f"ep01.{lang}.caption.srt"
    p_ass = dest / f"ep01.{lang}.ass"
    write_srt(p_spoken, spoken)
    write_srt(p_labeled, labeled)
    write_srt(p_caption, caption)
    write_ass(p_ass, [c for c in cues if str(c.get(text_key) or "").strip()], text_key)
    return [p_spoken, p_labeled, p_caption, p_ass]


def to_cast_plan(data: dict) -> dict:
    characters = []
    for row in data.get("speakers") or []:
        characters.append(
            {
                "id": row["id"],
                "display_name": row.get("display_zh") or row["id"],
                "gender": row.get("gender") or "unknown",
                "age": row.get("age"),
                "is_main": bool(row.get("is_main")),
                "role": row.get("speaker_type") or "character",
                "speaker_id": row["id"],
            }
        )
    cues_out = []
    for cue in data.get("cues") or []:
        cues_out.append(
            {
                "index": int(cue["index"]),
                "id": cue["id"],
                "shot_id": cue.get("shot_id"),
                "start_ms": int(cue["start_ms"]),
                "end_ms": int(cue["end_ms"]),
                "speaker_id": cue["speaker_id"],
                "named_speaker_id": cue["speaker_id"],
                "gender": next(
                    (
                        str(s.get("gender") or "unknown")
                        for s in data.get("speakers") or []
                        if s.get("id") == cue["speaker_id"]
                    ),
                    "unknown",
                ),
                "line_kind": cue.get("line_kind"),
                "delivery": cue.get("delivery"),
                "emotion": cue.get("emotion"),
                "zh_text": cue.get("text_zh") or "",
                "km_text": cue.get("text_km") or "",
                "caption_zh": cue.get("caption_zh") or "",
                "caption_km": cue.get("caption_km") or "",
            }
        )
    return {
        "schema": "cast_plan_v3",
        "cast_plan_version": 3,
        "source": "yuye_jinlian_cues_v1",
        "episode": data.get("episode"),
        "reference_mode": "external_voice_bank",
        "skip_diarization": True,
        "skip_source_vocals": True,
        "characters": characters,
        "cues": cues_out,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--cues",
        default="productions/004-yuye-jinlian/07-dubbing/ep01.cues.json",
    )
    args = p.parse_args()
    src = Path(args.cues).resolve()
    dest = src.parent
    data = json.loads(src.read_text(encoding="utf-8"))
    cues = list(data.get("cues") or [])
    written = export_lang(cues, dest, "zh")
    written += export_lang(cues, dest, "km")
    cast_path = dest / "ep01.cast_plan.json"
    cast_path.write_text(
        json.dumps(to_cast_plan(data), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    written.append(cast_path)
    for path in written:
        print(path)


if __name__ == "__main__":
    main()
