#!/usr/bin/env python3
"""Build EP01 resplit-v2 stills handoff. Does not touch the 29-shot lock."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from compile_episode_packages import compile_episode  # noqa: E402
from director.frame_desc import compile_frame_descriptions_from_table, render_frame_descriptions_md  # noqa: E402
from director.pipeline import write_artifact  # noqa: E402
from director.shot_table import sanitize_shot_table  # noqa: E402

PROD = ROOT / "productions" / "010-gongpai"
SRC = PROD / ".pipeline" / "shot_list.ep01.resplit-v2.json"
LABEL = "ep01-v2"

# 尾帧：end ≠ start（扔/捡/开柜/入袋/穿过/甩/翻面/手停住 + 过门槛/插入/挤进/抹/掉/拧/拖）
LAST = {
    "SH001", "SH002", "SH003", "SH005", "SH008", "SH013", "SH015", "SH016",
    "SH017", "SH018", "SH020", "SH021", "SH023", "SH028", "SH029", "SH040",
    "SH043", "SH051", "SH052", "SH060", "SH064",
}

# 走廊按厂门内侧夹道出图，不要用七线空镜
CORRIDOR = {f"SH{n:03d}" for n in range(41, 49)}

# 已映射 rewrite + 26 补词。track 是工作轨。
LINES = {
    "SH004": [("琳", "琳-独白", "怎么又裁人，我名字怎么排头一个……")],
    "SH005": [("琳", "琳-独白", "又是琳头一个到……临时扫地的就得早来。")],
    "SH006": [("琳", "琳-独白", "保安当我空气啊。")],
    "SH007": [("春安", "春安-口白", "琳，七线我春安管着，别在这儿晃，去把后面那间扫了。")],
    "SH008": [("春安", "春安-口白", "后面那间一年都没开过了，赶紧去。")],
    "SH009": [("春安", "春安-口白", "听见没有，快去。")],
    "SH010": [("琳", "琳-口白", "可七线地上的机油……")],
    "SH011": [("春安", "春安-口白", "机油放着自己会干，少管闲事。")],
    "SH013": [("琳", "琳-独白", "催催催……去就去。")],
    "SH014": [("琳", "琳-独白", "后面那间一年没开，扫完交差。")],
    "SH015": [("琳", "琳-独白", "锁都锈成这样了。")],
    "SH016": [("琳", "琳-独白", "灰比人还多。")],
    "SH017": [("琳", "琳-独白", "扫就扫，谁稀罕七线。")],
    "SH018": [("琳", "琳-独白", "窗台灰都能搓成条。")],
    "SH019": [("琳", "琳-独白", "脚印就我一个？这屋真一年没人进？")],
    "SH020": [("琳", "琳-独白", "这柜门还虚掩着？")],
    "SH021": [("琳", "琳-独白", "里面还能有什么……")],
    "SH022": [("琳", "琳-独白", "柜子里空的？怎么就塞了块烂牌子……")],
    "SH023": [("琳", "琳-独白", "灰厚得跟皮似的。")],
    "SH024": [("琳", "琳-独白", "波帕……常务副总？")],
    "SH025": [("琳", "琳-独白", "这哪是临时工带的牌子……")],
    "SH030": [("波帕", "波帕-口白", "我是波帕。你看得见我？")],
    "SH031": [("琳", "琳-口白", "你……你到底是人是……")],
    "SH032": [("波帕", "波帕-口白", "别嚷，全厂就你一个能看见我，跟别人说只会被当成中暑。")],
    "SH033": [("波帕", "波帕-口白", "跟别人说只会被当成中暑。")],
    "SH034": [("波帕", "波帕-口白", "跟别人说只会被当成中暑。")],
    "SH035": [("波帕", "波帕-口白", "听好，我们只有十五天时间。")],
    "SH037": [("女工", "女工-口白", "琳！赶紧出来！")],
    "SH038": [("琳", "琳-口白", "来了！")],
    "SH039": [("琳", "琳-独白", "她脚下怎么没有影子？")],
    "SH040": [("琳", "琳-独白", "先塞口袋，别让人看见。")],
    "SH041": [("琳", "琳-独白", "口袋鼓着这块牌，别掉出来。")],
    "SH042": [("琳", "琳-独白", "她直直朝波帕走过去……")],
    "SH045": [("琳", "琳-口白", "你没感觉吗？")],
    "SH046": [("琳", "琳-独白", "头都不偏一下，当空气走过去了。")],
    "SH047": [("琳", "琳-独白", "七线门口怎么那么多人。")],
    "SH048": [("琳", "琳-独白", "她们全围在我车边上？")],
    "SH049": [("琳", "琳-口白", "你们围着我车干什么？")],
    "SH050": [("琳", "琳-独白", "拉链一直敞着？")],
    "SH051": [("春安", "春安-口白", "车底下塞的什么？")],
    "SH052": [("春安", "春安-口白", "看见没有！")],
    "SH053": [("春安", "春安-口白", "节前丢的那批藏青布，吊牌都没拆，全在这车底下塞着！")],
    "SH055": [("春安", "春安-口白", "临时工手脚不干净，今天签了字赶紧滚！")],
    "SH056": [("春安", "春安-口白", "今天签了字赶紧滚！")],
    "SH057": [("琳", "琳-口白", "车子一直停在七线外边，底下敞着……我根本没……")],
    "SH059": [("琳", "琳-独白", "辞退单……")],
    "SH060": [("春安", "春安-口白", "笔给你拧开了。")],
    "SH061": [("琳", "琳-独白", "全厂都盯着我签字……")],
    "SH062": [("春安", "春安-口白", "愣着干什么，按手印签字！")],
    "SH063": [("波帕", "波帕-口白", "别认。")],
    "SH067": [("琳", "琳-独白", "不是我拿的，休想让我认。")],
}

FILL_26 = {
    "SH005", "SH006", "SH009", "SH014", "SH015", "SH016", "SH017", "SH018",
    "SH019", "SH020", "SH021", "SH023", "SH039", "SH040", "SH041", "SH042",
    "SH045", "SH046", "SH047", "SH048", "SH049", "SH050", "SH051", "SH052",
    "SH060", "SH061",
}

SCENE_PARENT = {
    "factory-gate": "02-assets/scenes/factory-gate/master.jpg",
    "storeroom": "02-assets/scenes/storeroom/master.jpg",
    "line-7": "02-assets/scenes/line-7/master.jpg",
}


def refs_for(shot: dict) -> list[dict]:
    sid = shot["shot_id"]
    out = []
    for character, track, line in LINES.get(sid, []):
        out.append({"character": character, "track": track, "line": line})
    return out


def still_parent_for(shot: dict, prev_id: str, is_scene_first: bool) -> str:
    sid = shot["shot_id"]
    if sid in CORRIDOR:
        return SCENE_PARENT["factory-gate"]
    if is_scene_first:
        loc = shot.get("location_id") or "factory-gate"
        if sid == "SH001":
            return SCENE_PARENT["factory-gate"]
        return SCENE_PARENT.get(loc, SCENE_PARENT["factory-gate"])
    folder = "04-frames/ep01-v2"
    if prev_id in LAST:
        return f"{folder}/{prev_id}-last.jpg"
    return f"{folder}/{prev_id}.jpg"


def build_table() -> dict:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    prev_id = ""
    prev_scene = ""
    for shot in data["shots"]:
        sid = shot["shot_id"]
        scene = shot.get("scene_id") or ""
        is_first = scene != prev_scene
        shot["dialogue_ref"] = refs_for(shot)
        if shot["dialogue_ref"]:
            tracks = {item["track"] for item in shot["dialogue_ref"]}
            shot["dialogue_delivery"] = "post"
            if any("独白" in t for t in tracks) and not any("口白" in t for t in tracks):
                shot["dialogue_delivery"] = "post"
        else:
            shot["dialogue_delivery"] = "none"
        shot["keyframe_plan"] = "first_last" if sid in LAST else "first"
        shot["still_parent"] = still_parent_for(shot, prev_id, is_first)
        prev_id = sid
        prev_scene = scene
    data["table_id"] = LABEL
    data["source"] = "shot_list.ep01.resplit-v2.json"
    data["keep_paper_duration"] = True
    data["locked_picture"] = False
    data["status"] = "ready"
    data["agent"] = "design"
    data["updated_at"] = int(time.time())
    writer = writer_from(data)
    return sanitize_shot_table(data, writer=writer), writer


def writer_from(table: dict) -> dict:
    scenes: dict[str, dict] = {}
    for shot in table.get("shots") or []:
        sid = shot.get("scene_id") or ""
        scene = scenes.setdefault(
            sid,
            {"scene_id": sid, "location_id": shot.get("location_id") or "", "dialogue": []},
        )
        if shot.get("location_id") and not scene.get("location_id"):
            scene["location_id"] = shot.get("location_id")
        for item in shot.get("dialogue_ref") or []:
            if item.get("line"):
                scene["dialogue"].append(
                    {"character": item.get("character") or "", "line": item["line"], "track": item.get("track") or ""}
                )
    return {
        "series_bible": {
            "logline": "工牌有鬼 EP01",
            "characters": [
                {"id": "rin", "name": "琳"},
                {"id": "chanthy", "name": "春安"},
                {"id": "bopha", "name": "波帕"},
                {"id": "worker", "name": "女工"},
                {"id": "guard", "name": "保安"},
            ],
            "locations": [
                {"id": "factory-gate", "name": "厂门"},
                {"id": "storeroom", "name": "杂物间"},
                {"id": "line-7", "name": "七线"},
            ],
        },
        "scenes": list(scenes.values()),
        "episode_outline": [{"title": "第 01 集 · resplit-v2"}],
        "origin": "ep01-v2-handoff",
    }


def write_dialogue_md(table: dict) -> None:
    kou, du = 0, 0
    lines = [
        "# 《工牌有鬼》EP01 resplit-v2 工作台词轨",
        "",
        "- **状态**：已挂进 `.pipeline/shot_list.ep01-v2.json`",
        "- **锁画**：29 镜活表 `.pipeline/shot_list.json` 不动",
        "- **开场**：SH001–SH003 无词（3 秒异常钩子）",
        "- **出场自报**：琳=SH005 / 春安=SH007 / 波帕=SH030",
        "- **硬句**：十五天=SH035 / 别认=SH063 / 不签=SH067",
        "- 台词是工作轨，禁止金句。走 Seedance 原声中文唇同步（speech_mode=seedance_native）：原句进 audio_block，说话人带 voice_card；H3 fallback 没有原声对白。",
        "",
    ]
    for shot in table["shots"]:
        sid = shot["shot_id"]
        lines.append(f"### {sid}")
        refs = shot.get("dialogue_ref") or []
        if not refs:
            lines.append("- track: —")
            lines.append("- text: （无词）")
            note = shot.get("dialogue_goes_to") or ""
            if note:
                lines.append(f"- note: {note}")
        for item in refs:
            track = item.get("track") or "—"
            lines.append(f"- track: {track}")
            lines.append(f"- text: {item.get('line')}")
            if "口白" in track:
                kou += 1
            elif "独白" in track:
                du += 1
            if sid in FILL_26:
                lines.append("- note: 本轮补词")
        lines.append("")
    lines.extend([
        "## 文末统计",
        "",
        f"口白条数：{kou}",
        f"独白条数：{du}",
        f"有词镜：{sum(1 for s in table['shots'] if s.get('dialogue_ref'))}",
        f"无词镜：{sum(1 for s in table['shots'] if not s.get('dialogue_ref'))}",
        f"补词 26 镜：{'、'.join(sorted(FILL_26))}",
        "",
    ])
    dest = PROD / "03-storyboard" / "ep01-dialogue-v2.md"
    dest.write_text("\n".join(lines), encoding="utf-8")


def write_job_sheet(table: dict, packages: dict) -> None:
    last_ids = [s["shot_id"] for s in table["shots"] if s.get("keyframe_plan") == "first_last"]
    pkg_by = {p["shot_id"]: p for p in packages.get("packages") or []}
    rows = []
    for shot in table["shots"]:
        sid = shot["shot_id"]
        pkg = pkg_by.get(sid) or {}
        parent = shot.get("still_parent") or ""
        last = "是" if sid in LAST else "—"
        allow = " --allow-master" if parent.startswith("02-assets/scenes/") else ""
        rows.append(
            f"| {sid} | `{parent}` | {last} | `{shot.get('still_start')}` | {shot.get('expression')} |{allow} |"
        )
    table_md = "\n".join(rows)
    last_csv = "、".join(last_ids)
    body = """# 交接 · EP01 resplit-v2 静帧（Codex 出图）

给 Codex。**只出首/尾帧静帧**，不出视频，不写 `shots.json`，不写 `keyframes.json` 的 pass，不锁新关，**不要动 29 镜锁画**。

项目：`productions/010-gongpai`  
表：`.pipeline/shot_list.ep01-v2.json`（67 镜，源 `.pipeline/shot_list.ep01.resplit-v2.json`）  
生成包：`.pipeline/gen_packages.ep01-v2.json`  
画面描述：`.pipeline/frame_descriptions.ep01-v2.json`  
台词：`03-storyboard/ep01-dialogue-v2.md`

**29 镜锁画不要碰：**

| 锁 | 路径 |
|---|---|
| 活表 | `.pipeline/shot_list.json`（`locked_picture=true`，29 镜） |
| 旧包 | `.pipeline/gen_packages.json` |
| 旧首尾帧 | `04-frames/SH*.jpg` |
| 旧成片 | `05-shots/SH*.mp4` |

本轮只写 **新文件夹**：

`productions/010-gongpai/04-frames/ep01-v2/SHxxx.jpg`  
有尾帧才写 `SHxxx-last.jpg`

成片画幅：**16:9**。落盘：`1672×941`。LOOK = **数字电影 CG**，不是写实。画面无汉字、无高棉文；台词是工作轨。

---

## 指针（导演台 / 脚本必须带标签）

```bash
# 落帧
python3 scripts/place_codex_frame.py \\
  --prod productions/010-gongpai \\
  --episode ep01-v2 \\
  --shot SH001 --slot first \\
  --parent 02-assets/scenes/factory-gate/master.jpg \\
  --allow-master \\
  --src "$CODEX_HOME/generated_images/那张图.png"

# 编包（已编好，不要用 --episode 1）
python3 scripts/compile_episode_packages.py \\
  --prod productions/010-gongpai \\
  --episode ep01-v2 \\
  --from-table
```

`--episode ep01-v2` 才会读写：

- `.pipeline/shot_list.ep01-v2.json`
- `.pipeline/gen_packages.ep01-v2.json`
- `04-frames/ep01-v2/`

`--episode 1` 仍指向 29 镜锁画，禁止用来出 v2 帧。

---

## 不准做

- 不覆盖 `04-frames/SH001.jpg` 等无后缀正式帧（那是另一版 29 切）。
- 不要把旧 SH001 成片首帧当父图。本版 SH001 是门房玻璃上的裁员名单，不是厂门推车。
- 不把首帧写进 `02-assets/`。不写 `03-storyboard/shots.json`。不出视频。
- 提示词禁止：`真人`、`photoreal`、`real person`、`live-action photograph`。
- **首帧 = t=0**。禁止把 `one_action` 的结果画进首帧（扔出去 / 捡入手 / 柜已开 / 牌已入袋 / 已穿过 / 已甩开 / 名单已翻面 / 手已停住）。
- 尾帧只在下表标「是」的镜：end state ≠ start state。
- 护照 / 空镜只参考人物和场景，**不跟父图文件比例走**。源图必须已经是 16:9（可裁，禁止拉伸）。

---

## 认脸 / 认场

| 人 | 护照 | 本集状态 |
|---|---|---|
| **rin / 琳** | `02-assets/characters/rin/master.jpg` + `face.jpg` | 发网、清洁短袖、旧围裙、胶鞋。可见工牌 **T-0417 / TEMP**，无名。 |
| **bopha / 波帕** | `02-assets/characters/bopha/master.jpg` + `face.jpg` | 暖金半透明、白长衫盖脚、无影、不见脚。SH026 才入画。 |
| **chanthy / 春安** | `02-assets/characters/chanthy/master.jpg` + `face.jpg` | 主管工装，干。 |

空镜（khmerless）：

| 场 | 空镜 | 谁用 |
|---|---|---|
| EP01_SC01 | `02-assets/scenes/factory-gate/master.jpg` | SH001 场第一镜。名单贴在**门房玻璃**上，用厂门空镜，不要文生名单特写底板（`layoff-list` 尚无道具图）。 |
| EP01_SC02 | `02-assets/scenes/storeroom/master.jpg` | SH016 场第一镜 |
| EP01_SC03 走廊 | `factory-gate/master.jpg` 内侧夹道 | **SH041–SH048** 父图用厂门空镜，不要用七线、不要用旧帧 |
| EP01_SC03 七线 | `02-assets/scenes/line-7/master.jpg` | SH049 起 |

道具：只有 `02-assets/props/bopha-badge/master.jpg`（拉丁 BOPHA / Deputy GM）。名单 / 辞退单 / 钥匙 / 扫把 / 藏青布 / 笔 **没有正式底板** — 字面虚或拉丁，禁止汉字和高棉文。

---

## 父图规则

- 场第一镜：该场空镜 + `--allow-master`
- 同场后续：上一镜 `-last.jpg`（没有则上一镜首帧）。`place_codex_frame.py --episode ep01-v2` 默认就是这样。
- 尾帧：默认本镜首帧（可省略 `--parent`）
- Codex `master` 只参考人物场景，place 必须走 `place_codex_frame.py`

SH001 父图选 **厂门空镜**（名单在门房玻璃上，空镜里已经有这块玻璃）。不要用旧 `04-frames/SH001.jpg`。

---

## 尾帧清单（LAST_COUNT 镜）

LAST_CSV

其余只要首帧。1 秒开场镜也要出首帧（静帧不受 Seedance 4 秒下限限制；视频以后按 4 秒渲再裁）。

---

## 逐镜

| 镜 | 父图 | 尾帧 | 首帧 t=0 | 脸 | place 额外 |
|---|---|---|---|---|---|
TABLE_ROWS

表情必须外放：愣 / 横 / 怕 / 讥 / 咬牙 / 眼瞪大 / 嘴扯开。禁止若有所思。

---

## 落盘命令样例

场 1 第一镜（名单，空镜）：

```bash
python3 scripts/place_codex_frame.py \\
  --prod productions/010-gongpai --episode ep01-v2 \\
  --shot SH001 --slot first \\
  --parent 02-assets/scenes/factory-gate/master.jpg --allow-master \\
  --src "$CODEX_HOME/generated_images/SH001.png"
```

SH001 尾帧（纸边已在微颤，手还没伸进来）：

```bash
python3 scripts/place_codex_frame.py \\
  --prod productions/010-gongpai --episode ep01-v2 \\
  --shot SH001 --slot last \\
  --src "$CODEX_HOME/generated_images/SH001-last.png"
```

同场后续（默认父图上一镜 `-last`，可省略 `--parent`）：

```bash
python3 scripts/place_codex_frame.py \\
  --prod productions/010-gongpai --episode ep01-v2 \\
  --shot SH002 --slot first \\
  --src "$CODEX_HOME/generated_images/SH002.png"
```

场 2 第一镜：

```bash
python3 scripts/place_codex_frame.py \\
  --prod productions/010-gongpai --episode ep01-v2 \\
  --shot SH016 --slot first \\
  --parent 02-assets/scenes/storeroom/master.jpg --allow-master \\
  --src "$CODEX_HOME/generated_images/SH016.png"
```

场 3 走廊第一镜（厂门内侧，不是七线）：

```bash
python3 scripts/place_codex_frame.py \\
  --prod productions/010-gongpai --episode ep01-v2 \\
  --shot SH041 --slot first \\
  --parent 02-assets/scenes/factory-gate/master.jpg --allow-master \\
  --src "$CODEX_HOME/generated_images/SH041.png"
```

七线建立：

```bash
python3 scripts/place_codex_frame.py \\
  --prod productions/010-gongpai --episode ep01-v2 \\
  --shot SH049 --slot first \\
  --parent 02-assets/scenes/line-7/master.jpg --allow-master \\
  --src "$CODEX_HOME/generated_images/SH049.png"
```

---

## Seedance 备注（本轮不出视频）

纸面 1s 开场合法。Seedance 2.0 单镜渲染下限 4 秒；包里 `duration_sec` 是纸面秒，`render_duration_sec` / `seedance_min_sec` 是以后渲视频用的。静帧不受此限。

生成包每镜有 `still_start` 语义（`image_prompt` + `frame_description`）、`state_note`、`continuity.binding`、`parent_hint`。≤5 张 ref。身份从 `02-assets` 来。
"""
    dest = PROD / "03-storyboard" / "codex-ep01-v2-stills.md"
    dest.write_text(
        body.replace("LAST_COUNT", str(len(last_ids))).replace("LAST_CSV", last_csv).replace("TABLE_ROWS", table_md),
        encoding="utf-8",
    )


def main() -> int:
    table, writer = build_table()
    missing = [sid for sid in FILL_26 if sid not in LINES]
    if missing:
        raise SystemExit(f"26 补词缺：{missing}")
    write_artifact(PROD, "writer.ep01-v2.json", writer)
    frames = compile_frame_descriptions_from_table(table)
    write_artifact(PROD, "frame_descriptions.ep01-v2.json", frames)
    write_artifact(PROD, "shot_list.ep01-v2.json", table)
    md = render_frame_descriptions_md(frames, title="第 01 集 · ep01-v2")
    (PROD / "03-storyboard" / "frame-descriptions.ep01-v2.md").write_text(md, encoding="utf-8")
    write_dialogue_md(table)
    frames_dir = PROD / "04-frames" / "ep01-v2"
    frames_dir.mkdir(parents=True, exist_ok=True)
    keep = frames_dir / ".gitkeep"
    if not keep.exists():
        keep.write_text("", encoding="utf-8")
    leftover = [p.name for p in frames_dir.glob("SH*.jpg")]
    if leftover:
        raise SystemExit(f"ep01-v2 里已经有旧 jpg，先清：{leftover[:8]}")
    result = compile_episode(PROD, LABEL, confirm=True, write=True, from_table=True)
    if not result.get("ok"):
        print(json.dumps({"ok": False, "errors": result.get("errors"), "warnings": result.get("warnings")}, ensure_ascii=False, indent=2))
        return 1
    write_job_sheet(result["table"], result["packages"])
    pkgs = result["packages"]["packages"]
    last_n = sum(1 for p in pkgs if p.get("keyframe_plan") == "first_last")
    kou = du = 0
    for shot in result["table"]["shots"]:
        for item in shot.get("dialogue_ref") or []:
            if "口白" in (item.get("track") or ""):
                kou += 1
            elif "独白" in (item.get("track") or ""):
                du += 1
    print(json.dumps({
        "ok": True,
        "shots": result["shot_count"],
        "packages": result["package_count"],
        "first_frames": result["shot_count"],
        "last_frames": last_n,
        "koubai": kou,
        "dubai": du,
        "fill_26": len(FILL_26),
        "wrote": result.get("wrote"),
        "warnings": result.get("warnings"),
        "dest": "04-frames/ep01-v2/",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
