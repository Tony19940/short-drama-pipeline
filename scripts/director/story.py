"""Gate 0 story intake: InkOS launch + export upload, or local file. Drafts until lock."""

from __future__ import annotations

import io
import json
import re
import time
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from .agents import migrated_story_view, story_migrated

SOURCE_DIR = "01-bible/source"
SCRIPT_HINTS = re.compile(
    r"(第\s*\d+\s*集|EP\s*\d+|INT\.|EXT\.|SH\d{3}|场次|分镜|FADE IN)",
    re.I,
)
CHAPTER_HINTS = re.compile(r"(第[一二三四五六七八九十百]+\s*章|^#+\s+第.+章)", re.M)


def source_root(prod: Path) -> Path:
    path = prod / SOURCE_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def classify_text(text: str) -> str:
    blob = text or ""
    if SCRIPT_HINTS.search(blob) and not CHAPTER_HINTS.search(blob[:2000]):
        return "script"
    if SCRIPT_HINTS.search(blob) and blob.count("SH") >= 3:
        return "script"
    return "novel"


def extract_text(filename: str, data: bytes) -> str:
    name = (filename or "upload.txt").lower()
    if name.endswith(".docx"):
        return _docx_text(data)
    if name.endswith(".pdf"):
        return _pdf_text(data)
    for enc in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _docx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = zf.read("word/document.xml")
    root = ET.fromstring(xml)
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paras = []
    for para in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
        texts = [node.text or "" for node in para.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")]
        line = "".join(texts).strip()
        if line:
            paras.append(line)
    return "\n".join(paras)


def _pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        PdfReader = None
    if PdfReader is not None:
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    # fallback: keep printable latin/utf8 runs
    raw = data.decode("latin-1", errors="ignore")
    chunks = re.findall(r"[\x20-\x7e\u4e00-\u9fff]{4,}", raw)
    return "\n".join(chunks[:4000])


def _outline_from(text: str, kind: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    heads = [line for line in lines if line.startswith("#") or re.match(r"第.+[章集]", line)]
    if not heads:
        heads = lines[:12]
    title = "小说大纲" if kind == "novel" else "剧本大纲"
    body = "\n".join(f"- {line.lstrip('#').strip()}" for line in heads[:24])
    return f"# {title}\n\n{body}\n"


def _characters_from(text: str) -> str:
    names = []
    for match in re.finditer(r"[\u4e00-\u9fff·]{2,8}|[A-Z][a-z]+(?:\s[A-Z][a-z]+)?", text[:8000]):
        token = match.group(0)
        if token not in names and token not in {"The", "She", "He", "INT", "EXT"}:
            names.append(token)
        if len(names) >= 16:
            break
    rows = "\n".join(f"| {name} | 待确认 | |" for name in names[:16]) or "| （未识别） | | |"
    return "# 人物草稿\n\n| 名字 | 功能 | 备注 |\n|---|---|---|\n" + rows + "\n"


def _timeline_from(text: str) -> str:
    beats = []
    for line in text.splitlines():
        if re.search(r"第.+[章集]|后来|第二天|三年|闪回", line):
            beats.append(line.strip())
        if len(beats) >= 12:
            break
    if not beats:
        beats = [line.strip() for line in text.splitlines() if line.strip()][:8]
    return "# 时间线草稿\n\n" + "\n".join(f"- {item}" for item in beats) + "\n"


def write_brief(prod: Path, payload: dict) -> dict:
    title = str(payload.get("title") or "").strip() or "未命名"
    logline = str(payload.get("logline") or "").strip()
    audience = str(payload.get("audience") or "金边竖屏短剧").strip()
    notes = str(payload.get("notes") or "").strip()
    body = (
        f"# 创意简报\n\n"
        f"- 标题：{title}\n"
        f"- 一句话：{logline or '（待补）'}\n"
        f"- 观众：{audience}\n"
        f"- 备注：{notes or '无'}\n\n"
        "## InkOS\n\n"
        "点「去 InkOS 写小说」会启动本机写作台（默认 http://127.0.0.1:4567/）。"
        "导演台不代写、不登录。写完导出后再回到本页上传。\n"
    )
    dest = source_root(prod) / "brief.draft.md"
    dest.write_text(body, encoding="utf-8")
    return snapshot_story(prod)


def ingest_upload(prod: Path, filename: str, data: bytes) -> dict:
    if not data:
        raise ValueError("空文件")
    text = extract_text(filename, data).strip()
    if not text:
        raise ValueError("读不出文字。请导出成 md/txt 再传。")
    kind = classify_text(text)
    root = source_root(prod)
    (root / "original.draft.md").write_text(f"# 原文 · {filename}\n\n{text}\n", encoding="utf-8")
    (root / "story-outline.draft.md").write_text(_outline_from(text, kind), encoding="utf-8")
    (root / "characters.draft.md").write_text(_characters_from(text), encoding="utf-8")
    (root / "timeline.draft.md").write_text(_timeline_from(text), encoding="utf-8")
    meta = {
        "filename": filename,
        "kind": kind,
        "chars": len(text),
        "ingested_at": int(time.time()),
        "note": "小说请先改编再进编剧；已是分集剧本可直接锁故事关。",
    }
    (root / "source.draft.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return snapshot_story(prod)


def promote_story_drafts(prod: Path) -> None:
    root = source_root(prod)
    mapping = [
        ("brief.draft.md", "brief.md"),
        ("source.draft.json", "source.json"),
        ("original.draft.md", "original.md"),
        ("story-outline.draft.md", "story-outline.md"),
        ("characters.draft.md", "characters.md"),
        ("timeline.draft.md", "timeline.md"),
    ]
    for src_name, dest_name in mapping:
        src = root / src_name
        if src.exists() and src.stat().st_size > 0:
            dest = root / dest_name
            dest.write_bytes(src.read_bytes())


def snapshot_story(prod: Path) -> dict:
    root = prod / SOURCE_DIR
    official = {}
    drafts = {}
    if root.exists():
        for path in sorted(root.iterdir()):
            if not path.is_file() or path.name == ".DS_Store":
                continue
            rel = f"{SOURCE_DIR}/{path.name}"
            if ".draft." in path.name:
                drafts[path.name] = path.read_text(encoding="utf-8")
            else:
                official[path.name] = path.read_text(encoding="utf-8")
    kind = ""
    if "source.json" in official:
        try:
            kind = json.loads(official["source.json"]).get("kind") or ""
        except json.JSONDecodeError:
            kind = ""
    elif "source.draft.json" in drafts:
        try:
            kind = json.loads(drafts["source.draft.json"]).get("kind") or ""
        except json.JSONDecodeError:
            kind = ""
    migrated = story_migrated(prod)
    return {
        "dir": SOURCE_DIR,
        "kind": kind,
        "official": official,
        "drafts": drafts,
        "migrated": migrated,
        "migrated_view": migrated_story_view(prod) if migrated else None,
        "ready": bool(official.get("source.json") and official.get("original.md")) or migrated,
    }
