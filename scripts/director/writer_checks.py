"""Episode-level writer checks. Warnings for drafts; do not invent a second contract."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

UNFILMABLE = re.compile(
    r"千军|万人|爆炸崩塌|穿越时空|巨型龙|全城|航拍城市|换脸直播|粒子海洋"
)


def _text(prod: Path, rel: str) -> str:
    path = prod / rel
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def check_episode(prod: Path, shots: Optional[list[dict]] = None) -> list[str]:
    episode = _text(prod, "01-bible/ep01.md")
    blueprint = _text(prod, "01-bible/blueprint.md")
    blob = episode + "\n" + blueprint
    issues: list[str] = []
    if blob.strip():
        head = episode[:400] or blob[:400]
        if not re.search(r"冲突|砸|罚|跪|不认|丢工|揭穿|钩|替人|开除|认脸|银铃|烧|吊桥|退路|死守", head):
            issues.append("开场 5 秒附近看不到能看见的冲突或反差")
        if re.search(r"从前有个人|很久以前|大段旁白介绍|风景空镜", blob[:500]):
            issues.append("开场像说明书或风景片，改成当场发生的事")
        if not re.search(
            r"推进|后来|于是|下一|直到|终于|然后|接着|送走|打晕|换墙|点将|守墙|烧桥|烧掉|递|问守",
            blob,
        ):
            issues.append("中段缺少可看见的情节推进")
        if not re.search(r"高潮|爆发|摊牌|揭|打|哭|认|送走|抬上|换墙|第三道|铜铃", blob):
            issues.append("小高潮不明显")
        tail = episode[-500:] or blob[-500:]
        if not re.search(r"钩|下集|未完|悬|门外|铃|还没", tail):
            issues.append("尾钩弱或看不到下一集牵引")
        if UNFILMABLE.search(blob):
            issues.append("可能有 AI 难拍场面（人海/大破坏），改成可锁的小动作")
    if shots:
        kinds = {str(shot.get("line_kind") or "") for shot in shots}
        if kinds and not (kinds & {"dialogue", "inner", "inner_voice"}):
            issues.append("本集没有口述或心里台词，观众很难入戏")
        first = shots[0] if shots else {}
        if first and str(first.get("line_kind") or "") == "narration" and len(str(first.get("line") or "")) > 24:
            issues.append("第一镜旁白偏长，开场会像说明书")
        for shot in shots:
            line = str(shot.get("line") or "")
            sec = int(shot.get("seconds") or 0) or 1
            kind = str(shot.get("line_kind") or "")
            limit = max(18, sec * 5)
            if kind in {"dialogue", "inner", "inner_voice"} and len(line) > limit:
                issues.append(f"{shot.get('id')} 台词偏长，配不上 {sec} 秒")
            if kind in {"narration"} and len(line) > max(24, sec * 6):
                issues.append(f"{shot.get('id')} 旁白偏长，配不上 {sec} 秒")
    return issues
