#!/usr/bin/env python3
"""EP01 resplit-v2: write per-shot acting (behavior, not feelings) into the 67-shot candidate table
and recompile its packages with Seedance native speech. Does not touch the 29-shot lock, stills, or clips.

Acting fields per character: want / hide (inner line) + business / muscle / change (what the camera sees).
`expression` is rewritten to the visible part only. `manner` rides on the dialogue_ref item and goes
into the audio block (「用普通话{manner}说」).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from compile_episode_packages import compile_episode  # noqa: E402
from director.acting import acting_warnings  # noqa: E402
from director.pipeline import read_artifact, write_artifact  # noqa: E402

PROD = ROOT / "productions" / "010-gongpai"
LABEL = "ep01-v2"
TABLE = "shot_list.ep01-v2.json"

# shot_id -> {"acting": {角色: {...}}, "expression": 可见表情, "manner": 台词语气}
ACTING: dict[str, dict] = {
    "SH002": {
        "acting": {"琳": {"business": "手伸向玻璃上的名单", "muscle": "指尖离纸一寸骤停，手指微张", "change": "伸出去的手停住，再往前一寸都没有"}},
        "expression": "无脸只手骤停",
    },
    "SH004": {
        "acting": {"琳": {"want": "看清是不是自己的名字", "hide": "其实已经认出来了", "business": "空手，双手还搭在车把上", "muscle": "眼瞪到最大，下巴微张，呼吸停半拍", "change": "眼钉在名单最上一行不动"}},
        "expression": "琳眼瞪大下巴微张",
        "manner": "低声自语地",
    },
    "SH005": {
        "acting": {"琳": {"want": "把车弄进去别耽误", "hide": "刚看到的名字", "business": "双手压车把，前轮顶在门槛上", "muscle": "咬牙，肩往前顶，胶鞋蹬地一下", "change": "车轮跳过门槛，人跟着往前一冲"}},
        "expression": "琳咬牙肩前顶",
        "manner": "边推车边嘟囔着",
    },
    "SH006": {
        "acting": {
            "琳": {"want": "让保安看她一眼", "hide": "被当空气的委屈", "business": "一手推车", "muscle": "转头，眼先扫过去，头再跟着偏过去", "change": "看完一眼收回目光继续推"},
            "保安": {"business": "低头翻本子", "muscle": "头不抬，只有手指翻页", "change": "始终不动"},
        },
        "expression": "琳转头瞪一眼保安",
        "manner": "小声地",
    },
    "SH007": {
        "acting": {
            "春安": {"want": "先压住琳", "hide": "钥匙一年没动过的事", "business": "旧钥匙摊在手心里举到胸前", "muscle": "下巴抬着，眼皮压下来看琳，嘴角往下", "change": "钥匙从垂着的手举到胸口"},
            "琳": {"business": "双手握车把", "muscle": "眼落到钥匙上，肩收紧", "change": "脚步停住"},
        },
        "expression": "春安下巴抬着举钥匙",
        "manner": "压着嗓子慢慢地",
    },
    "SH008": {
        "acting": {
            "春安": {"want": "把她打发到后面那间", "hide": "不想多说一个字", "business": "手心里的钥匙", "muscle": "手腕一甩，钥匙脱手飞向琳脚边；甩完手不收回，指着地", "change": "钥匙从手里到地上"},
            "琳": {"business": "握车把", "muscle": "眼跟着钥匙落到地上，身子微缩", "change": "视线从春安的脸落到脚边"},
        },
        "expression": "春安甩手扔钥匙",
        "manner": "扬着嗓子催着",
    },
    "SH009": {
        "acting": {
            "春安": {"want": "话说完了，走人", "business": "空手，手在身侧", "muscle": "肩先转，脚跟拧地，整个背对过来", "change": "从面对琳到只剩背影"},
            "琳": {"business": "握车把", "muscle": "眼盯她背影，嘴闭紧", "change": "站着没动"},
        },
        "expression": "春安转身背对",
        "manner": "头也不回地",
    },
    "SH010": {
        "acting": {
            "琳": {"want": "把机油的事说出来", "hide": "怕多嘴", "business": "一手离开车把抬起半截", "muscle": "嘴张大喊出半句，身子前倾一步", "change": "话到半截停住，抬起的手悬着"},
            "春安": {"business": "背影走远", "muscle": "脚步不停", "change": "越走越远"},
        },
        "expression": "琳嘴张大身前倾",
        "manner": "扬起声追着",
    },
    "SH011": {
        "acting": {
            "春安": {"want": "把她顶回去", "business": "空手往前走", "muscle": "头不回，肩不动，只有嘴在说，脚步慢半拍再走", "change": "脚步慢半拍又继续"},
            "琳": {"business": "手悬在半空", "muscle": "半句停在嘴边，嘴没合上", "change": "手慢慢放下"},
        },
        "expression": "春安背影开口不回头",
        "manner": "背着身",
    },
    "SH012": {
        "acting": {"琳": {"want": "追上去", "hide": "不敢", "business": "手还悬着", "muscle": "咬牙，牙关鼓起，鼻息一重，脚没迈", "change": "从要追到站住"}},
        "expression": "琳咬牙鼻息重",
    },
    "SH013": {
        "acting": {"琳": {"want": "拿了钥匙走", "hide": "咽下去的那口气", "business": "弯腰去捡脚边钥匙", "muscle": "眼瞪着钥匙，弯腰一把抓起", "change": "钥匙从地上到手里"}},
        "expression": "琳瞪眼弯腰抓钥匙",
        "manner": "嘟囔着",
    },
    "SH014": {
        "acting": {"琳": {"want": "扫完交差", "business": "右手攥钥匙，左手推车", "muscle": "步子急，肩前倾，咬牙", "change": "从原地到夹道深处"}},
        "expression": "琳急步咬牙",
        "manner": "边走边小声",
    },
    "SH015": {
        "acting": {"琳": {"business": "钥匙对准锁孔", "muscle": "手在锁孔前顿一下再插进去", "change": "钥匙从半空插进锁"}},
        "expression": "无脸只手急",
        "manner": "低声自语地",
    },
    "SH016": {
        "acting": {"琳": {"want": "进去看看有多糟", "business": "空手，肩先进门", "muscle": "侧身，肩挤进门框，眼瞪开扫屋里", "change": "从门槛外到门内"}},
        "expression": "琳瞪眼挤进门框",
        "manner": "刚进门小声",
    },
    "SH017": {
        "acting": {"琳": {"want": "快扫快完", "business": "抓起墙边扫把", "muscle": "手一把抓住扫把杆，扫把头对准窗台", "change": "扫把从墙边到手里"}},
        "expression": "琳抓扫把对准窗台",
        "manner": "嘟囔着",
    },
    "SH018": {
        "acting": {"琳": {"business": "扫把在手，往墙角扫", "muscle": "咬牙，一下一下扫，扫出一条灰线", "change": "灰从窗台到墙角柜前"}},
        "expression": "琳咬牙扫灰",
        "manner": "边扫边小声",
    },
    "SH020": {
        "acting": {"琳": {"business": "手伸向虚掩的柜门", "muscle": "手在柜门前慢下来，指尖搭上门边", "change": "手从半空搭上柜门"}},
        "expression": "无脸只手",
        "manner": "低声自语地",
    },
    "SH021": {
        "acting": {"琳": {"want": "看看里面有什么", "business": "手搭在柜门上", "muscle": "一把拉开，柜门吱一声，眼跟着探进去", "change": "柜门从虚掩到全开，灰工牌露出"}},
        "expression": "琳拉开柜门探头",
        "manner": "自言自语地",
    },
    "SH022": {
        "acting": {"琳": {"business": "手还搭在柜门上", "muscle": "眼瞪大，目光钉在灰工牌上，嘴微张", "change": "从看柜到钉住工牌"}},
        "expression": "琳眼瞪大嘴微张",
        "manner": "低声自语地",
    },
    "SH023": {
        "acting": {"琳": {"business": "拇指按上工牌的灰皮", "muscle": "拇指一抹，灰掉一道", "change": "字面从灰到露出一半"}},
        "expression": "无脸只手",
        "manner": "低声自语地",
    },
    "SH025": {
        "acting": {"琳": {"want": "把名字念出来", "business": "旧牌捧在手里", "muscle": "低头，眼瞪着牌面，睫毛不动", "change": "目光钉在字面上不动"}},
        "expression": "琳低头瞪牌",
        "manner": "低声念着",
    },
    "SH026": {
        "acting": {
            "琳": {"business": "手里旧牌", "muscle": "低头不动", "change": "背后柜缝亮起一线光"},
            "波帕": {"muscle": "只有胸口透光，不见脸，不动", "change": "从无到透光"},
        },
        "expression": "琳低头不动波帕不见脸",
    },
    "SH027": {
        "acting": {"琳": {"business": "旧牌在手", "muscle": "猛回头，眼瞪到最大，脖子先转身子后跟", "change": "从背对到看见"}},
        "expression": "琳猛回头眼瞪大",
    },
    "SH028": {
        "acting": {"琳": {"business": "扫把还在手里", "muscle": "后退一步背撞上柜门，脸拧起来，嘴张开没出声", "change": "从站着到撞上柜"}},
        "expression": "琳退撞柜门脸拧起来",
    },
    "SH029": {
        "acting": {"琳": {"business": "扫把", "muscle": "手一松，扫把滑出手掌掉到脚边", "change": "扫把从手到地"}},
        "expression": "无脸",
    },
    "SH030": {
        "acting": {
            "波帕": {"want": "让她确认看得见", "muscle": "半身侧脸逼近半步，嘴开口，眼盯着琳", "change": "从不开口到开口"},
            "琳": {"business": "手里旧牌", "muscle": "贴着柜门，肩缩起", "change": "身子往柜门贴得更紧"},
        },
        "expression": "波帕侧脸逼近开口",
        "manner": "气声平平地",
    },
    "SH031": {
        "acting": {
            "琳": {"want": "问她是什么", "hide": "腿在抖", "business": "手里旧牌攥紧", "muscle": "嘴张开结巴，眼瞪大，下巴抖", "change": "问句到半截停住"},
            "波帕": {"muscle": "不动，等她问完", "change": "眼皮都没抬"},
        },
        "expression": "琳嘴张开结巴",
        "manner": "结巴着",
    },
    "SH032": {
        "acting": {
            "波帕": {"want": "一句话把规则说完", "muscle": "侧脸不动，只有嘴在说，气声，眼不眨", "change": "话说完仍半身"},
            "琳": {"business": "手里旧牌", "muscle": "贴柜门，眼瞪着她", "change": "肩一点点松下来"},
        },
        "expression": "波帕侧脸气声开口",
        "manner": "压着气声",
    },
    "SH033": {
        "acting": {
            "波帕": {"muscle": "又逼近半步，脸更近，嘴慢慢说", "change": "距离缩到一臂内"},
            "琳": {"business": "手里旧牌", "muscle": "头往后缩，眼没离开她", "change": "后脑碰到柜门"},
        },
        "expression": "波帕贴得更近",
        "manner": "贴近了低声",
    },
    "SH034": {
        "acting": {
            "波帕": {"muscle": "半身不动，嘴角平，气声把话说完", "change": "话落，停住"},
            "琳": {"business": "手里旧牌", "muscle": "眨眼，喉头动一下", "change": "从瞪着到眨眼"},
        },
        "expression": "波帕嘴角平气声",
        "manner": "气声慢慢地",
    },
    "SH035": {
        "acting": {
            "波帕": {"want": "把十五天钉进她脑子里", "muscle": "再贴近，脚不见，衣摆飘一下，嘴说完停住", "change": "十五天说完，距离最近"},
            "琳": {"business": "手里旧牌", "muscle": "贴柜门不动，眼瞪着", "change": "呼吸变快"},
        },
        "expression": "波帕贴到最近",
        "manner": "一字一顿地",
    },
    "SH036": {
        "acting": {"琳": {"want": "说点什么", "hide": "说不出", "business": "手里旧牌", "muscle": "咬住下唇，眼瞪着，喉头咽一下", "change": "从要开口到咽回去"}},
        "expression": "琳咬住下唇",
    },
    "SH037": {
        "acting": {
            "琳": {"want": "别被门外的人发现", "business": "旧牌在手", "muscle": "猛回头看中偏左的门，肩一抖", "change": "从看波帕到看门"},
            "波帕": {"muscle": "不动，只看琳"},
        },
        "expression": "琳猛回头看门",
        "manner": "隔着门大声",
    },
    "SH038": {
        "acting": {
            "琳": {"want": "把门外的人应付走", "business": "旧牌在手", "muscle": "朝门口张嘴喊一声，身子往门口偏", "change": "喊完转回来"},
            "波帕": {"muscle": "不动"},
        },
        "expression": "琳朝门张嘴应",
        "manner": "朝门口高声",
    },
    "SH039": {"expression": "无脸", "manner": "屏着气低声"},
    "SH040": {
        "acting": {
            "琳": {"want": "藏好这块牌", "business": "旧牌塞进围裙口袋", "muscle": "手一按口袋，牌进去，手在口袋外拍一下", "change": "牌从手里到口袋，口袋略鼓"},
            "波帕": {"muscle": "看着她的手"},
        },
        "expression": "琳塞牌拍口袋",
        "manner": "压低声音",
    },
    "SH041": {
        "acting": {
            "琳": {"want": "快出去别露馅", "business": "一手按着围裙口袋", "muscle": "急步踏出门，眼瞪着前方", "change": "从门内到走廊"},
            "波帕": {"muscle": "跟在她右侧，漂着", "change": "跟出门"},
            "女工": {"muscle": "在深处走", "change": "越走越近"},
        },
        "expression": "琳急步瞪眼按口袋",
        "manner": "边走边小声",
    },
    "SH042": {
        "acting": {
            "女工": {"muscle": "沿轴直走，头不偏，步子不变", "change": "从深处走到波帕身前"},
            "琳": {"business": "手按口袋", "muscle": "眼瞪大，脚停住", "change": "从走到站住"},
            "波帕": {"muscle": "站在轴上不动"},
        },
        "expression": "女工直走琳眼瞪大",
        "manner": "屏着气小声",
    },
    "SH043": {
        "acting": {
            "女工": {"muscle": "肩穿进白衬衫再穿出，头一下都不偏，步子不变", "change": "从波帕身前到身后"},
            "波帕": {"muscle": "不动，衣摆被穿过处微微起伏", "change": "衣摆起伏一下又平"},
        },
        "expression": "女工头不偏穿过",
    },
    "SH044": {
        "acting": {"琳": {"want": "喊出来", "hide": "喊不出", "business": "手按口袋", "muscle": "眼瞪大，嘴张开，没有声音，喉头动", "change": "从看到穿过到张嘴"}},
        "expression": "琳眼瞪大嘴张开",
    },
    "SH045": {
        "acting": {
            "琳": {"want": "问她怎么没感觉", "business": "手按口袋", "muscle": "回头死盯波帕，眼瞪着，嘴张着问", "change": "从看走廊到看波帕"},
            "波帕": {"muscle": "不转头，只有眼皮动一下", "change": "眼皮动一下"},
        },
        "expression": "琳回头瞪波帕",
        "manner": "压着声音",
    },
    "SH046": {
        "acting": {
            "女工": {"muscle": "头不回，脚步不停，走出画右", "change": "从画中到出画"},
            "琳": {"business": "手按口袋", "muscle": "眼跟着她出画", "change": "目光跟到画边"},
            "波帕": {"muscle": "不动"},
        },
        "expression": "女工头不回出画",
        "manner": "小声地",
    },
    "SH047": {
        "acting": {"琳": {"business": "胶鞋", "muscle": "急踩一步，鞋底拍地", "change": "脚从原地迈向门口"}},
        "expression": "无脸只脚急",
        "manner": "低声自语地",
    },
    "SH048": {
        "acting": {"琳": {"business": "肩", "muscle": "肩擦过门框", "change": "门框从肩前到肩后"}},
        "expression": "无脸只肩",
        "manner": "低声自语地",
    },
    "SH049": {
        "acting": {
            "琳": {"want": "弄明白她们围着车干什么", "business": "手按围裙口袋", "muscle": "脚步停住，眼扫一圈围观的人，肩缩", "change": "从走到站住"},
            "春安": {"business": "手搭在清洁车顶", "muscle": "站在车边不动", "change": "等她过来"},
            "女工": {"muscle": "半圆围着，眼都看琳", "change": "目光从车转到琳"},
            "波帕": {"muscle": "贴琳右肩", "change": "跟着停住"},
        },
        "expression": "琳脚停眼扫一圈",
        "manner": "声音发抖地",
    },
    "SH050": {"expression": "无脸", "manner": "低声自语地"},
    "SH051": {
        "acting": {"春安": {"want": "把布亮出来", "business": "手伸进车底层抓布", "muscle": "手臂一拽，藏青布从底层拖出半截", "change": "布从车底到手里"}},
        "expression": "春安拽布",
        "manner": "扬着声",
    },
    "SH052": {
        "acting": {"春安": {"business": "手里的藏青布", "muscle": "手一甩，布落地铺开，吊牌朝上", "change": "布从手到地上"}},
        "expression": "无脸只布",
        "manner": "大声地",
    },
    "SH053": {
        "acting": {
            "春安": {"want": "当众定她的罪", "business": "手指直指地上的布", "muscle": "手臂伸直指着布，下巴朝琳一抬，字字砸出来", "change": "从指布到指琳"},
            "琳": {"business": "手按口袋", "muscle": "眼跟着她的手指落到布上", "change": "目光从春安到布"},
        },
        "expression": "春安伸臂指布",
        "manner": "一字一字砸着",
    },
    "SH054": {
        "acting": {"女工": {"muscle": "几个人的头齐齐转向地上的布，眼都落下去", "change": "目光从琳到布"}},
        "expression": "围观齐齐转头看布",
    },
    "SH055": {
        "acting": {
            "春安": {"want": "把临时工三个字钉在她身上", "business": "手收回叉在腰上", "muscle": "嘴角往下，眼皮压着看琳，说完不眨眼", "change": "手从指布到叉腰"},
            "琳": {"business": "手按口袋", "muscle": "嘴闭着，眼瞪大", "change": "肩缩紧"},
        },
        "expression": "春安叉腰压眼皮",
        "manner": "拖着腔",
    },
    "SH056": {
        "acting": {
            "春安": {"want": "今天就把她赶走", "muscle": "跨半步逼近，手往机台方向一挥", "change": "距离缩短半步"},
            "琳": {"business": "手按口袋", "muscle": "退不出去，肩缩", "change": "身子往后仰一点"},
        },
        "expression": "春安跨步逼近挥手",
        "manner": "提高嗓门",
    },
    "SH057": {
        "acting": {"琳": {"want": "把话说完", "hide": "自己都不信能说完", "business": "手按口袋", "muscle": "嘴张开，话说一半，眼瞪着春安，喉头动", "change": "话说到半截声音散了"}},
        "expression": "琳张嘴辩解",
        "manner": "声音发抖地",
    },
    "SH058": {
        "acting": {"琳": {"business": "手按口袋", "muscle": "眼从春安落到车的方向，嘴慢慢闭上", "change": "视线换了方向"}},
        "expression": "琳眼落向车",
    },
    "SH059": {"expression": "无脸", "manner": "低声自语地"},
    "SH060": {
        "acting": {"春安": {"business": "笔", "muscle": "两指拧开笔帽，笔放回纸边", "change": "笔帽从合到开"}},
        "expression": "无脸只手拧笔帽",
        "manner": "顺口",
    },
    "SH061": {
        "acting": {
            "琳": {"want": "不碰那支笔", "hide": "全场的眼", "business": "手伸到桌边", "muscle": "手在桌边僵住，指尖离笔一寸，呼吸停", "change": "手从伸出到停住"},
            "春安": {"business": "手叉腰", "muscle": "站着等"},
            "女工": {"muscle": "半圆不动，看她的手"},
            "波帕": {"muscle": "贴琳右肩"},
        },
        "expression": "琳手僵在桌边",
        "manner": "嗓子发干地",
    },
    "SH062": {
        "acting": {
            "春安": {"want": "逼她按下去", "business": "手掌", "muscle": "手掌拍一下机台，身子前倾，眼瞪着琳", "change": "从等到拍台"},
            "琳": {"business": "手僵在桌边", "muscle": "肩一抖", "change": "手往回缩一寸"},
            "女工": {"muscle": "半圆不动"},
            "波帕": {"muscle": "贴琳右肩不动"},
        },
        "expression": "春安拍台前倾",
        "manner": "拍着机台喊着",
    },
    "SH063": {
        "acting": {
            "波帕": {"want": "让她别认", "muscle": "贴到琳右肩，嘴凑近她耳边，气声两个字", "change": "从站到贴肩"},
            "琳": {"business": "手仍在桌边", "muscle": "眼瞪大，手不动", "change": "呼吸停一下"},
            "春安": {"business": "手叉腰", "muscle": "只盯琳"},
        },
        "expression": "波帕贴右肩气声琳眼瞪大",
        "manner": "贴着耳朵气声",
    },
    "SH064": {
        "acting": {
            "女工": {"muscle": "有人从波帕身上穿过去，头不偏，脚不停", "change": "从波帕身前到身后"},
            "波帕": {"muscle": "不动", "change": "衣摆起伏一下"},
            "琳": {"business": "手仍在桌边", "muscle": "眼跟着穿过去的人", "change": "目光跟到人走开"},
            "春安": {"business": "手叉腰", "muscle": "不动"},
        },
        "expression": "围观穿过波帕琳眼跟着",
    },
    "SH065": {
        "acting": {"琳": {"want": "不签", "business": "手垂在身侧", "muscle": "抬眼，咬牙，牙关鼓起，眼直视春安方向", "change": "从低头到抬眼"}},
        "expression": "琳抬眼咬牙",
    },
    "SH067": {
        "acting": {
            "琳": {"want": "不签", "hide": "腿还在抖", "business": "空手垂在身侧，手不碰笔", "muscle": "站直，咬牙，下巴抬起，眼直视", "change": "从手在桌边到手垂下"},
            "春安": {"business": "手叉腰", "muscle": "嘴闭紧"},
            "波帕": {"muscle": "贴琳右肩不动"},
            "女工": {"muscle": "半圆不动"},
        },
        "expression": "琳站直咬牙抬下巴",
        "manner": "咬着牙一字一句地",
    },
}


def apply_acting(table: dict) -> dict:
    touched = 0
    for shot in table.get("shots") or []:
        sid = shot.get("shot_id")
        patch = ACTING.get(sid)
        if not patch:
            continue
        if patch.get("acting"):
            shot["acting"] = patch["acting"]
        if patch.get("expression"):
            shot["expression"] = patch["expression"]
        manner = patch.get("manner")
        if manner:
            for item in shot.get("dialogue_ref") or []:
                if isinstance(item, dict) and item.get("line"):
                    item["manner"] = manner
        touched += 1
    return {"touched": touched, "with_acting": sum(1 for s in table.get("shots") or [] if s.get("acting"))}


def main() -> int:
    table = read_artifact(PROD, TABLE)
    if not table.get("shots"):
        raise SystemExit(f"missing {TABLE}")
    if table.get("locked_picture") is True:
        raise SystemExit("this is the locked picture table; acting only goes on the candidate table")
    before = {s["shot_id"]: (s.get("expression"), s.get("one_action"), s.get("dialogue_ref")) for s in table["shots"]}
    stats = apply_acting(table)
    leftover = acting_warnings(table["shots"])
    write_artifact(PROD, TABLE, table)
    result = compile_episode(PROD, LABEL, confirm=True, write=True, from_table=True)
    if not result.get("ok"):
        print(json.dumps({"ok": False, "errors": result.get("errors"), "warnings": result.get("warnings")}, ensure_ascii=False, indent=2))
        return 1
    pkgs = result["packages"]["packages"]
    print(json.dumps({
        "ok": True,
        "shots": result["shot_count"],
        "packages": result["package_count"],
        "acting_shots": stats["with_acting"],
        "acting_adjective_warnings": leftover,
        "audio_blocks": sum(1 for p in pkgs if p.get("audio_block")),
        "native_line_shots": sum(1 for p in pkgs if p.get("dialogue_lines")),
        "max_motion_chars": max(p.get("motion_prompt_chars") or 0 for p in pkgs),
        "over_limit": [p["shot_id"] for p in pkgs if (p.get("motion_prompt_chars") or 0) > 500],
        "trimmed": {p["shot_id"]: p["motion_prompt_trimmed"] for p in pkgs if p.get("motion_prompt_trimmed")},
        "voice_cards": result.get("voice_cards"),
        "wrote": result.get("wrote"),
        "before_after_sample": {
            sid: {"before": before[sid][0], "after": ACTING[sid]["expression"]}
            for sid in ("SH007", "SH028", "SH062")
        },
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
