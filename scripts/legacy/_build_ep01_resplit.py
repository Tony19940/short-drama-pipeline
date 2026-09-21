#!/usr/bin/env python3
"""One-shot builder: EP01 paper resplit candidate. Does not touch official tables."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

from director.defaults import PACE_ASL_MAX, PACE_ASL_MIN, PACE_SPM_MAX, PACE_SPM_MIN
from director.pipeline import read_artifact
from director.shot_table import needed_seconds, pace_metrics, sanitize_shot_table, store_duration, validate_shot_table
from director.video_profiles import get_profile

PROD = ROOT / "productions" / "010-gongpai"
OUT_JSON = PROD / ".pipeline" / "shot_list.ep01.resplit.json"
OUT_MD = PROD / "03-storyboard" / "ep01-resplit.md"


def inherit(parent: dict, **over) -> dict:
    shot = copy.deepcopy(parent)
    shot.pop("shot_id", None)
    if "dialogue_ref" not in over:
        shot["dialogue_ref"] = []
        shot["dialogue_delivery"] = "none"
    if "state_changes" not in over:
        shot["state_changes"] = []
    shot["internal_cuts"] = []
    shot.update(over)
    shot["action_ref"] = shot.get("one_action")
    return shot


def set_in_frame(shot: dict, **flags) -> None:
    state = shot.get("state")
    if not isinstance(state, dict):
        return
    chars = state.get("characters")
    if not isinstance(chars, dict):
        return
    for cid, flag in flags.items():
        item = chars.get(cid)
        if isinstance(item, dict):
            item["in_frame"] = flag


def set_note(shot: dict, note: str) -> None:
    state = shot.get("state")
    if isinstance(state, dict):
        state["note"] = note


def main() -> None:
    official = json.loads((PROD / ".pipeline" / "shot_list.json").read_text(encoding="utf-8"))
    by_old = {s["shot_id"]: s for s in official["shots"]}
    specs = [
        # SC01
        ("SH001", "SH001", 6.0, "master", "wide",
         "琳把清洁车从近处推向厂门纵深卡住旧门槛再推进去",
         "信息在连续时间里：进厂建立，卡门槛是同一动作过程，不拆",
         "建立压到 6s，过程不拆", None, {"visual_turn": True, "hardest": False}),
        ("SH002", "SH002", 2.2, "insert", "medium",
         "琳的目光停在离职名单最上面自己的名字",
         "让观众读清离职名单最上是琳的名字",
         "物件插入，压秒", None, {"visual_turn": True}),
        ("SH003", "SH003", 2.2, "single", "full",
         "琳推清洁车经过不抬头的保安",
         "坐实她被无视，保安连头都不抬",
         "一动作压秒", None, {}),
        ("SH004", "SH004", 3.5, "single", "medium",
         "春安把旧钥匙扔到琳脚边",
         "物件过手：钥匙离手落地。扔的过程不中途切",
         "从复合镜拆出扔+落地，飞行中不拆",
         [{"character": "春安", "line": "后面那间，一年没人进。你去扫。"}],
         {"hardest": True, "visual_turn": True, "state_changes": ["chanthy.carrying"],
          "in_from": "春安侧身面向琳，旧钥匙还在她手里，尚未出手",
          "out_to": "钥匙停在琳脚边地上，春安还没走远",
          "body_facing": "四分之三", "camera_side": "front-right"}),
        ("SH005", "SH004", 2.5, "single", "full",
         "春安转身朝夹道深处走",
         "支开落在背影上，扔和走拆开",
         "物件落地后的走是第二件事",
         None,
         {"hardest": False, "visual_turn": False, "state_changes": [],
          "in_from": "钥匙已在琳脚边地上，春安开始转身",
          "out_to": "春安背影朝画右深处",
          "left": "琳、清洁车、地上的钥匙", "right": "春安转完身的背影",
          "body_facing": "四分之三", "camera_side": "front-right",
          "dialogue_goes_to": ""}),
        ("SH006", "SH005", 3.0, "single", "full",
         "琳对着已经转身的春安开口",
         "琳想把七线问完",
         "对白换说话人，琳的半句单独一镜",
         [{"character": "琳", "line": "七线那边的油……"}],
         {"in_from": "钥匙还在脚边，春安已转身", "out_to": "话只说出半截，春安不回头"}),
        ("SH007", "SH005", 3.0, "reverse", "medium",
         "春安头也不回把油顶回去",
         "春安一句顶回，不回头",
         "换说话人",
         [{"character": "春安", "line": "油会自己干。"}],
         {"in_from": "琳的半句还在空气里", "out_to": "春安头也不回往画右深处走",
          "scale": "medium", "coverage_type": "reverse"}),
        ("SH008", "SH005", 1.8, "reaction", "close",
         "琳听完没再跟上",
         "对白后无词反应单独成立",
         "必须单独成立的反应",
         None,
         {"in_from": "油会自己干刚落下", "out_to": "琳停在近脸，没跟上",
          "left": "琳脸", "right": "", "eyeline": "琳看春安背影方向",
          "hide": {"chanthy": False}}),
        ("SH009", "SH006", 2.2, "single", "medium",
         "琳弯腰捡起脚边旧钥匙",
         "物件过手：钥匙离地入手",
         "捡和走拆开",
         None,
         {"state_changes": ["rin.carrying"], "visual_turn": True,
          "in_from": "钥匙仍在脚边地上，她尚未弯腰",
          "out_to": "钥匙已在手里", "move_type": "static", "move_needed": "static", "move_reason": ""}),
        ("SH010", "SH006", 4.0, "follow", "wide",
         "琳推车走向夹道尽头",
         "结束在她独自拿着旧钥匙走向夹道尽头",
         "捡完再走是第二件事",
         None,
         {"state_changes": [], "visual_turn": True,
          "in_from": "钥匙已在手里，车在身边",
          "out_to": "她拿着旧钥匙走向尽头，接杂物间",
          "move_type": "track", "move_needed": "move",
          "move_reason": "不跟着走就看不见她独自走向夹道尽头"}),
        # SC02
        ("SH011", "SH007", 7.0, "master", "medium",
         "琳握扫把从窗台扫到墙角脚印只有她自己",
         "信息在连续时间里：脚印要扫够才读得清",
         "长镜头留住，压到 7s",
         None, {"move_type": "track", "move_needed": "move"}),
        ("SH012", "SH008", 1.8, "insert", "insert",
         "琳的手搭上虚掩柜门",
         "开柜动作起：手搭上门，门尚未拉开",
         "从 SH008 拆出动作起",
         None,
         {"in_from": "柜门仍虚掩，手尚未搭上", "out_to": "手搭在虚掩柜门上，柜内看不见工牌",
          "left": "铁皮柜门、手", "right": "", "body_facing": "无人", "camera_side": "front",
          "eyeline": "柜门", "visual_turn": False, "key_sfx": []}),
        ("SH013", "SH008", 2.2, "single", "medium",
         "琳拉开虚掩铁皮柜露出灰工牌",
         "开柜结果：没有布，只有灰工牌",
         "拉开过程不中途切",
         None,
         {"in_from": "手已搭在虚掩柜门上，柜内暗", "out_to": "柜门已开，灰工牌在柜内"}),
        ("SH014", "SH008", 1.5, "reaction", "close",
         "琳看见空柜和灰工牌",
         "空柜入眼，反应单独成立",
         "新信息点换了：空柜 vs 下一步抹灰",
         None,
         {"in_from": "柜已开，她刚看见", "out_to": "目光钉在灰工牌上",
          "left": "琳脸", "right": "柜内", "eyeline": "柜内灰工牌"}),
        ("SH015", "SH009", 2.2, "insert", "insert",
         "她随手一抹灰掉了姓名Bopha与职务常务副总读清",
         "抹灰读清姓名职务，证据入画",
         "抹灰过程不拆，可读后立刻切",
         None, {"visual_turn": True}),
        ("SH016", "SH010", 2.0, "close", "close",
         "琳低头看刚抹净的波帕旧牌尚未转身",
         "琳的脸还没看见身后",
         "压秒，纯视线",
         None, {}),
        ("SH017", "SH011", 4.0, "single", "medium",
         "柜缝里灯管从白衫胸口透出她仍低头看牌没有转身",
         "信息在连续时间里：透身要给读",
         "透身留住，3–4s",
         None, {"hardest": True, "visual_turn": True}),
        ("SH018", "SH012", 1.5, "reaction", "close",
         "琳发觉背后有人",
         "怕单独成立，尚未撞柜",
         "从 SH012 前拆出反应",
         None,
         {"in_from": "透胸刚看见，她尚未退", "out_to": "眼猛地看向身后，身体还没撞",
          "state_changes": [], "key_sfx": [],
          "left": "琳脸", "right": "肩后暖金", "eyeline": "猛地看向身后偏右"}),
        ("SH019", "SH012", 2.2, "reaction", "close",
         "琳退撞画左柜门扫把落地",
         "那一颗：怕从她脸上读出，扫把掉",
         "撞柜仍是全场最紧，过程不拆",
         None,
         {"state_changes": ["rin.carrying"], "visual_turn": True,
          "in_from": "她已看见身后，尚未退撞", "out_to": "她撞完，扫把在脚边"}),
        ("SH020", "SH013", 3.0, "single", "medium",
         "波帕半身侧脸开口脚不在画里",
         "半身开口第一句，不见正脸护照",
         "对白句进 2.5–4.5 桶",
         [{"character": "波帕", "line": "你看得见我。"}],
         {}),
        ("SH021", "SH014", 3.0, "reverse", "medium",
         "琳盯着她结巴开口",
         "琳一句问，无尖叫",
         "对白句压秒",
         [{"character": "琳", "line": "你、你谁——"}],
         {}),
        ("SH022", "SH015", 4.0, "single", "medium",
         "波帕自报全厂只有你看得见",
         "可见规则落地，仍半身",
         "从 12s 复合对白拆出第一信息",
         [{"character": "波帕", "line": "波帕。全厂只有你看得见。"}],
         {"in_from": "她问完", "out_to": "规则第一句落下，仍半身"}),
        ("SH023", "SH015", 5.0, "reverse", "medium",
         "波帕说别对别人说",
         "第二句换了信息种类：威胁/保密",
         "同一人第二句换信息就换镜",
         [{"character": "波帕", "line": "别对别人说。说了，他们只会当你中暑。"}],
         {"in_from": "全厂只有你看得见刚落", "out_to": "话说完，仍半身，脚不在画里",
          "left": "琳", "right": "波帕半身"}),
        ("SH024", "SH015", 1.5, "reaction", "close",
         "琳听完规则还没动",
         "对白后无词反应",
         "下一镜换题目（门外喊），反应必须单独成立",
         None,
         {"in_from": "规则说完", "out_to": "琳停在近脸，还没往门口看",
          "left": "琳脸", "right": "", "eyeline": "琳看波帕"}),
        ("SH025", "SH016", 2.5, "master", "full",
         "门外喊她的名字",
         "门外喊琳，牌还在手里",
         "门喊和塞袋拆开",
         None,
         {"state_changes": [], "visual_turn": False,
          "in_from": "旧牌仍在手里，门还没人喊", "out_to": "喊名落下，牌还在手里",
          "key_sfx": ["门外喊她"]}),
        ("SH026", "SH016", 2.2, "single", "medium",
         "她把波帕旧牌塞进围裙口袋",
         "物件入袋必须入画",
         "物件过手 / 入袋",
         None,
         {"state_changes": ["rin.carrying"], "visual_turn": True,
          "in_from": "旧牌仍在手里，喊名刚落", "out_to": "口袋略鼓，旧牌已不在手里",
          "key_sfx": []}),
        # SC03
        ("SH027", "SH017", 4.0, "master", "full",
         "女工从走廊深处沿轴走近波帕身前尚未穿过",
         "交代走廊轴：走近，尚未穿过",
         "压秒，不要 6s 等人走过来",
         None, {}),
        ("SH028", "SH018", 7.0, "single", "medium",
         "女工的肩穿进波帕白衬衫再穿出头都没偏脚步不停",
         "信息在连续时间里：穿过的进与出必须一镜内完成",
         "穿过禁止拆",
         None, {"visual_turn": True, "hardest": False}),
        ("SH029", "SH019", 1.8, "reaction", "close",
         "琳看着眼在动嘴没张",
         "穿过完成后给琳一眼",
         "反应压秒",
         None, {}),
        ("SH030", "SH020", 2.2, "single", "medium",
         "波帕不回头只有琳回头看她",
         "确认别人当空气",
         "视线转换单独一镜",
         None, {}),
        ("SH031", "SH020", 2.0, "follow", "full",
         "女工出画脚步不停",
         "穿过了还在走，落幅读清",
         "可选刀：只在穿过落幅读不清时加，本表加上以免空持",
         None,
         {"in_from": "琳已回头", "out_to": "女工出画，脚步不停",
          "left": "走廊近处", "right": "女工沿轴出画", "eyeline": "女工看前方"}),
        ("SH032", "SH021", 4.5, "master", "full",
         "七线门口半圆围人清洁车停在中间",
         "地理 master：半圆围观是墙，车在中间",
         "建立 3–5s",
         None,
         {"out_to": "围人可读，拉链还没给特写"}),
        ("SH033", "SH021", 1.8, "insert", "insert",
         "清洁车拉链未拉",
         "车拉链未拉，给观众先看见",
         "物件插入，从围人地理拆出",
         None,
         {"in_from": "车在中间，拉链尚未占画", "out_to": "拉链未拉可读",
          "left": "清洁车拉链", "right": "", "body_facing": "无人", "camera_side": "front",
          "eyeline": "", "key_sfx": [], "visual_turn": True}),
        ("SH034", "SH022", 2.5, "insert", "insert",
         "春安从车底层拖出藏青布甩在地上吊牌朝上可读形",
         "赃物落地：布和吊牌必须读清",
         "过程不拆",
         None, {"visual_turn": True}),
        ("SH035", "SH023", 4.0, "otc", "otc",
         "春安指着地上的布说藏青和吊牌在车底",
         "指控句一：藏青 / 吊牌 / 车底",
         "从 12s 指控拆出第一信息",
         [{"character": "春安", "line": "节前丢的那批，在她车里。"}],
         {"in_from": "布已在地上", "out_to": "句一落下，春安仍在越肩"}),
        ("SH036", "SH023", 1.8, "reaction", "medium",
         "围观一眼看向地上的布",
         "围观反应单独成立",
         "必须单独成立的反应",
         None,
         {"in_from": "句一刚落", "out_to": "围观目光钉在布上",
          "left": "围观的脸", "right": "地上的布", "eyeline": "看地上的布",
          "body_facing": "四分之三", "coverage_type": "reaction", "scale": "medium",
          "dialogue_ref": [], "dialogue_delivery": "none",
          "hide": {"chanthy": False, "rin": False, "worker": True}}),
        ("SH037", "SH023", 5.5, "otc", "otc",
         "春安说临时工不干净今天签字今天走",
         "指控句二：签字滚蛋",
         "同一人第二句换信息种类",
         [{"character": "春安", "line": "临时工，手脚比机器还快。今天签字，今天走。"}],
         {"in_from": "围观一眼刚切走", "out_to": "指控句说完，春安仍在越肩"}),
        ("SH038", "SH024", 3.0, "reaction", "close",
         "琳开口想说车一直停着",
         "琳想辩解",
         "从 SH024 拆出开口",
         [{"character": "琳", "line": "车……车一直停在——"}],
         {"in_from": "指控刚落", "out_to": "话只说出半截",
          "state_changes": [], "hide": {"chanthy": False}}),
        ("SH039", "SH024", 1.8, "close", "close",
         "话散了眼神从春安落到车的方向",
         "辩解失败，视线转换",
         "话散了是第二件事",
         None,
         {"in_from": "半句还在嘴边", "out_to": "眼神停在车的方向",
          "left": "琳脸", "right": "车的方向", "eyeline": "车的方向",
          "dialogue_ref": [], "dialogue_delivery": "none",
          "hide": {"chanthy": False}}),
        ("SH040", "SH025", 1.8, "insert", "insert",
         "离职书摊在十四号机台面上",
         "先给纸",
         "从摊书拧帽拆出纸",
         None,
         {"in_from": "台面还没有摊开的书", "out_to": "辞退单已摊开，笔帽未拧",
          "left": "摊开的离职书", "right": "", "key_sfx": [], "visual_turn": True}),
        ("SH041", "SH025", 1.8, "insert", "insert",
         "笔帽拧开",
         "再给拧开的笔帽",
         "物件过手；纸和帽都能读",
         None,
         {"in_from": "纸已摊开，笔帽未拧", "out_to": "笔帽已开，笔尖不落纸",
          "left": "笔", "right": "摊开的纸", "key_sfx": ["笔帽拧开"], "visual_turn": True}),
        ("SH042", "SH026", 4.5, "single", "medium",
         "全场等她她的手在桌边不动",
         "信息在连续时间里：对峙里权力没切点",
         "对峙留白，不和别认叠",
         None,
         {"dialogue_ref": [], "dialogue_delivery": "none",
          "in_from": "笔帽已开，手还没伸", "out_to": "手仍在桌边不动",
          "state_changes": ["rin.carrying"]}),
        ("SH043", "SH026", 2.5, "single", "medium",
         "春安逼她签字",
         "春安一句：签",
         "换说话人，从复合镜拆出",
         [{"character": "春安", "line": "签。"}],
         {"in_from": "全场还在等", "out_to": "签字落下",
          "state_changes": [], "left": "琳、清洁车", "right": "春安中景"}),
        ("SH044", "SH026", 2.5, "single", "medium",
         "波帕贴在她右肩说别认",
         "波帕只对琳说别认",
         "换说话人；不和等签、穿过叠",
         [{"character": "波帕", "line": "别认。"}],
         {"in_from": "签字刚落，手仍不动", "out_to": "别认落下，手仍不动",
          "state_changes": [], "left": "琳、波帕贴其右肩", "right": "春安虚"}),
        ("SH045", "SH026", 2.0, "single", "full",
         "别人从波帕身上穿过去看热闹",
         "有人穿过看热闹，不和别认叠",
         "三件事拆开，穿过单独一镜",
         None,
         {"in_from": "别认刚落", "out_to": "有人从波帕身上穿过去",
          "left": "琳、波帕贴右肩", "right": "穿过的围观",
          "dialogue_ref": [], "dialogue_delivery": "none"}),
        ("SH046", "SH027", 1.5, "reaction", "close",
         "琳抬眼",
         "琳抬眼，视线不落笔尖",
         "反应压到 1.2–1.8",
         None, {"hide": {"chanthy": False}}),
        ("SH047", "SH028", 6.5, "insert", "insert",
         "笔还在桌上没有手伸过来笔尖不落纸",
         "信息在连续时间里：笔尖悬停是那一颗",
         "笔尖不拆，5–6.5s",
         None, {"hardest": True, "visual_turn": True}),
        ("SH048", "SH029", 2.5, "master", "medium",
         "她站着没签围观还在",
         "峰值后回中景：这一天还没死",
         "回中景钩子，压秒",
         None, {}),
    ]

    notes = {
        "SH004": "扔必须入画：钥匙离手、落地。琳在画左，清洁车在身边；春安车间主管工装。春安还没走。胸前 T-0417 / TEMP。",
        "SH005": "钥匙已在地上。春安转完身朝画右深处，正打全身不是过肩。名单、保安不得入画。",
        "SH008": "只琳近脸。春安不入画，只靠眼神看背影方向。胸前 T-0417 / TEMP。",
        "SH036": "围观看地上的布。春安不到特写、不入近景。波帕本镜不抢画。",
        "SH039": "只琳近脸，车不入画，只靠眼神落到身侧车的方向。口袋略鼓干装。",
        "SH043": "春安中景不到特写；琳手不伸向笔；围观是墙。波帕贴右肩但不抢这句。",
        "SH044": "波帕贴琳右肩暖金只在衣缘，下摆盖脚无影，不越轴；琳手不伸向笔。",
    }

    dialogue_to: dict[str, list[str]] = {}
    shots = []
    cards = []
    for new_id, old_id, dur, cov, scale, action, job, why, dlg, extra in specs:
        parent = by_old[old_id]
        extra = dict(extra)
        hide = extra.pop("hide", None)
        over = {
            "shot_id": new_id,
            "duration_sec": dur,
            "coverage_type": cov,
            "scale": scale,
            "one_action": action,
            "shot_job": job,
            "from_old": old_id,
            "split_reason": why,
        }
        if "scale" in extra:
            over["scale"] = extra.pop("scale")
        if "coverage_type" in extra:
            over["coverage_type"] = extra.pop("coverage_type")
        goes = extra.pop("dialogue_goes_to", None)
        if dlg:
            over["dialogue_ref"] = dlg
            over["dialogue_delivery"] = "post"
            for item in dlg:
                dialogue_to.setdefault(f"{item['character']}：{item['line']}", []).append(new_id)
        over.update(extra)
        shot = inherit(parent, **over)
        if hide:
            set_in_frame(shot, **hide)
        if new_id in notes:
            set_note(shot, notes[new_id])
        need = needed_seconds(shot)
        if _sec(shot.get("duration_sec")) + 0.05 < need:
            shot["duration_sec"] = store_duration(need)
        shots.append(shot)
        cards.append(
            {
                "id": new_id,
                "from_old": old_id,
                "scene": shot["scene_id"],
                "duration": shot["duration_sec"],
                "coverage": shot["coverage_type"],
                "scale": shot["scale"],
                "one_action": action,
                "who": "、".join(
                    f"{d['character']}：{d['line']}" for d in (shot.get("dialogue_ref") or [])
                )
                or "—",
                "why": why,
                "in_from": shot.get("in_from"),
                "out_to": shot.get("out_to"),
                "dialogue_goes_to": "、".join(d["character"] + "→" + new_id for d in (shot.get("dialogue_ref") or []))
                or (goes if goes else "—"),
            }
        )

    def _pad_cap(shot: dict) -> float:
        cov = shot.get("coverage_type")
        job = shot.get("shot_job") or ""
        if shot.get("dialogue_ref"):
            return max(4.5, needed_seconds(shot))
        if cov == "reaction":
            return 2.0
        if cov == "insert" and "信息在连续时间里" not in job:
            return 2.5
        if "信息在连续时间里" in job:
            return 8.0
        return 5.0

    def _pad_to_band(rows: list[dict], target: float = 166.0) -> None:
        metrics = pace_metrics(rows)
        while metrics["total_sec"] < target:
            grew = False
            for shot in rows:
                cap = _pad_cap(shot)
                cur = float(shot["duration_sec"])
                if cur + 0.05 >= cap:
                    continue
                shot["duration_sec"] = store_duration(min(cap, cur + 0.5))
                grew = True
                metrics = pace_metrics(rows)
                if metrics["total_sec"] >= target:
                    return
            if not grew:
                return

    _pad_to_band(shots)
    for card, shot in zip(cards, shots):
        card["duration"] = shot["duration_sec"]

    payload = copy.deepcopy(official)
    payload["shots"] = shots
    payload["status"] = "candidate"
    payload["locked_picture"] = False
    payload["resplit_of"] = "shot_list.json"
    payload["origin"] = "shot-split-proposal-2026-09-11"
    payload["picture_table"] = "shot_list.json"
    payload["agent"] = "design"
    payload["notes"] = (
        "EP01 纸面重拆候选。活表 .pipeline/shot_list.json 仍是锁画表。"
        "对白与 SRT 仍按旧镜号。未进新表、不回炉、不重渲。"
    )
    payload["scene_plan"] = [
        {"scene_id": "EP01_SC01", "target_shots": 10, "target_sec": 32, "beats": official["scene_plan"][0]["beats"]},
        {"scene_id": "EP01_SC02", "target_shots": 16, "target_sec": 50, "beats": official["scene_plan"][1]["beats"]},
        {"scene_id": "EP01_SC03", "target_shots": 22, "target_sec": 78, "beats": official["scene_plan"][2]["beats"]},
    ]
    writer = read_artifact(PROD, "writer.json")
    payload = sanitize_shot_table(payload, writer=writer)
    payload["status"] = "candidate"
    payload["locked_picture"] = False
    payload["resplit_of"] = "shot_list.json"
    payload["picture_table"] = "shot_list.json"
    sets = json.loads((PROD / "03-storyboard" / "sets.json").read_text(encoding="utf-8"))
    look = (PROD / "02-assets" / "LOOK.md").read_text(encoding="utf-8")
    errors, warnings = validate_shot_table(
        payload,
        writer=writer,
        sets=sets,
        profile=get_profile(payload.get("target_model") or "seedance_2_0"),
        look_text=look,
        prod=PROD,
    )
    metrics = pace_metrics(payload["shots"])
    payload["warnings"] = warnings
    payload["pace"] = metrics
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    old_line_map = []
    for old in official["shots"]:
        for item in old.get("dialogue_ref") or []:
            old_line_map.append((old["shot_id"], item.get("character"), item.get("line")))

    def dests_for(who: str, line: str) -> list[str]:
        hit: list[str] = []
        seen: set[str] = set()
        for shot in payload["shots"]:
            for dref in shot.get("dialogue_ref") or []:
                dline = dref.get("line") or ""
                if dref.get("character") != who:
                    continue
                if dline == line or dline in (line or "") or (line or "") in dline:
                    sid = shot["shot_id"]
                    if sid not in seen:
                        seen.add(sid)
                        hit.append(sid)
        return hit

    lines = [
        "# EP01 纸面重拆候选",
        "",
        "状态：**candidate**。活表 `.pipeline/shot_list.json`（29 镜）仍是锁画表。",
        "本表不覆盖官方 `04-frames/*.jpg`、`05-shots/SH*.mp4`、SRT。",
        "对白工作轨 / SRT 仍按 **旧镜号**。PM 说进新表之前不重生成 SRT。",
        "",
        f"- 候选路径：`.pipeline/shot_list.ep01.resplit.json`",
        f"- 镜数：**{metrics['shots']}**（目标 46–52，工作约 48）",
        f"- 纸面秒：**{metrics['total_sec']}** · ASL **{metrics['asl']}s** · SPM **{metrics['spm']}**",
        f"- 目标带：SPM {PACE_SPM_MIN}–{PACE_SPM_MAX} · ASL {PACE_ASL_MIN}–{PACE_ASL_MAX}s",
        f"- 校验 errors：{len(errors)} · warnings：{len(warnings)}",
        "",
        "## 总表",
        "",
        "| 新镜 | from_old | 场 | 秒 | 覆盖 | 景别 | one_action | 对白 | dialogue_goes_to | 为何拆 |",
        "|---|---|---|---:|---|---|---|---|---|---|",
    ]
    for card in cards:
        action = card["one_action"].replace("|", "／")
        who = (card["who"] or "—").replace("|", "／")
        why = card["why"].replace("|", "／")
        goes = card["dialogue_goes_to"]
        lines.append(
            f"| {card['id']} | {card['from_old']} | {card['scene']} | {card['duration']} | "
            f"{card['coverage']} | {card['scale']} | {action} | {who} | {goes} | {why} |"
        )
    lines += [
        "",
        "## 旧镜对白去向",
        "",
        "| 旧镜 | 角色 | 原句 | 新镜 |",
        "|---|---|---|---|",
    ]
    for old_id, who, line in old_line_map:
        hit = dests_for(who, line or "")
        lines.append(f"| {old_id} | {who} | {(line or '').replace('|', '／')} | {'、'.join(hit) or '—'} |")
    lines += [
        "",
        "## 逐镜卡片",
        "",
    ]
    for card in cards:
        lines += [
            f"### {card['id']} · {card['scene']} · {card['duration']}s · from {card['from_old']}",
            "",
            f"- **one_action**：{card['one_action']}",
            f"- **in_from**：{card['in_from']}",
            f"- **out_to**：{card['out_to']}",
            f"- **who**：{card['who']}",
            f"- **dialogue_goes_to**：{card['dialogue_goes_to']}",
            f"- **为何拆**：{card['why']}",
            "",
        ]
    if errors:
        lines += ["## 校验 errors", ""] + [f"- {e}" for e in errors] + [""]
    if warnings:
        lines += ["## 校验 warnings（节选）", ""] + [f"- {w}" for w in warnings[:40]] + [""]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"json": str(OUT_JSON), "md": str(OUT_MD), "metrics": metrics, "errors": errors, "warnings": warnings[:24]}, ensure_ascii=False, indent=2))
    if errors:
        sys.exit(1)


def _sec(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


if __name__ == "__main__":
    main()
