# 两次审计后的流水线升级

本轮升级代码与交接协议，使用现有媒体做回归；没有重新拆《一瑞尔》分镜，没有生成新图片或提交付费视频。两次审计原文见 `pipeline-audit-2026-10-05.md` 和 `pipeline-audit-second-review-2026-10-05.md`。

## 现在的主路径

```text
登记 production / episode / revision
  → 草稿分镜 + 少量关键事件 + 段落理解问题
  → critic 建议 / 可全否决 → 人工创作审阅 → Gate C
  → 生成包确认 + 当前关键帧字节审核
  → 实际声画 animatic 构建及审阅
  → 付费生成（快照消费时和真正提交前均重新核验）
  → 原片技术 / 画面 / 适用表演层审核 + 关键事件原片观察
  → EDL 保留事件区间、顺序、声音、速度与输出帧时长
  → 具体导出影片 → 不读剧本的段落理解及声音审阅
  → Gate F 人工锁定
```

生成成功、文件存在、ASR 命中、哈希相同都不代表观众理解。设计审核、原片观察、成片理解三份证据分别保存，不相互替代。

## 版本与审核证据

`.pipeline/revisions.json` 是登记版的唯一入口，指向该版分镜、帧目录、视频目录、EDL 与审核文件。登记版缺文件或版本不明时阻断，不借用无后缀旧表。无登记的旧项目明确标 `legacy`，保留历史布局。完整登记方法见 [REVISION-BINDINGS.md](REVISION-BINDINGS.md)。

```bash
python3 scripts/register_revision.py --prod productions/<slug> --revision v3 register \
  --artifact-token ep01-v3 \
  --artifact shot_list.json=.pipeline/shot_list.ep01-v3.json \
  --frames-dir 04-frames/ep01-v3 --shots-dir 05-shots/ep01-v3 \
  --cut-file .pipeline/cut.ep01-v3.json --activate
python3 scripts/check_prod.py --prod productions/<slug> --episode 1 --revision v3
```

检查器输出实际版本、文件路径、SHA-256、镜数。旧锁不会迁移为新批准；缺指纹的旧锁保持过期。当前 gate 锁仍共用一组键，支持逐版批准；切换登记信息会使旧指纹保守失效，尚不支持两版并行保留独立锁。

草稿不再自动填 `pass`、完成全部设计步骤或宣布钩子落地。critic 可输出 `recommend`、`needs_rework`、`reject_all`；规则兜底只提供待审建议。登记版 Gate C 需要真人审阅者、结论、分镜内容指纹及事件合同指纹。修改合同使审核失效。

关键帧、单镜审核必须存在并覆盖实际执行镜号。登记版审核绑定当前媒体 hash；换图、换 take、换音轨不会沿用旧审核。技术或画面失败不能被顶层 `qc.status=pass` 掩盖；表演层仅在适用或明确要求时强制。

animatic 审批需要实际可播放 MP4、构建记录、影片和输入 hash、审阅者与看片结论。有对白/声音要求时必须提供实际音轨。旧 `input_only` 记录可以读取，不能授权收费生成。

## 少量关键事件，不建立庞大的世界状态库

`events.json` 的 schema 为 `narrative-events-v1`。每个重要段落列镜号、观众应能回答的问题、允许悬念和容易误读之处；只给不可丢的核心证据建立事件。

```json
{
  "schema": "narrative-events-v1",
  "sequences": [{
    "sequence_id": "return-reveal",
    "shot_ids": ["SH014", "SH015", "SH016", "SH017"],
    "understanding_questions": ["钱为什么出现？怎样知道此前没有这些钱？"],
    "allowed_uncertainty": ["能力的来历尚未知"],
    "misread_risks": ["钱原本藏在头盔里"]
  }],
  "events": [{
    "event_id": "coin-trigger",
    "sequence_id": "return-reveal",
    "shot_ids": ["SH015"],
    "channel": "visual",
    "required": true,
    "expected_observation": "暗哑铜钱亮起",
    "min_visible_sec": 0.15,
    "depends_on": []
  }]
}
```

`min_visible_sec` 由该事件需要确定，不是通用电影标准。`depends_on` 明确表示前置事件完成后再开始；需要同时发生的事件不要套用这个顺序约束。正常省略、悬念和连续动作可以成立，不要求把数钞、收手或每句对白后的反应逐项补镜。

`event_evidence.json` 保存**实际原片观察**：合同 hash、事件/镜号、素材路径及 hash、`start_sec/end_sec`、检查方法、检查者、时间和具体描述。Prompt 与设计尾帧不能当原片观察。缺观察为 `pending`；观察窗口被剪掉、变速后停留不足、前置顺序倒置或源片变化为失败。声音事件检查实际采用的声音区间；静音片段不能保留声音事件。

EDL 支持视频和声音分别指定 source/take 与 in/out，可保留 J/L cut。`speed` 同时进入事件投影与实际 FFmpeg 变速；`fps/output_duration_sec` 绑定输出帧时长，避免累计时长用一套公式、导出用另一套。更换实际采用 take 时必须审核那份素材。

## 导出与真正的段落审核

```bash
# 查看当前合同和审核输入指纹
python3 scripts/pipeline_review.py --prod productions/<slug> show
# 单纯检查：失败或待审返回非零，绝不写 pass
python3 scripts/pipeline_review.py --prod productions/<slug> check --report /tmp/check.json
# 实际检查者填写 JSON 后才记录创作审阅、原片观察或段落审阅
python3 scripts/pipeline_review.py --prod productions/<slug> design --input /tmp/design-review.json
python3 scripts/pipeline_review.py --prod productions/<slug> observe --input /tmp/event-observation.json
python3 scripts/pipeline_review.py --prod productions/<slug> sequence --input /tmp/sequence-review.json
# 本地候选，不替换正式 EDL 或批准
python3 scripts/assemble_episode.py --prod productions/<slug> --candidate
# 正式审片导出：先要求实际采用素材审核和关键事件保留
python3 scripts/assemble_episode.py --prod productions/<slug>
```

创作审阅输入需要 `reviewer/notes/input_sha256/contract_sha256`；可显式指定 `draft_file=.pipeline/shot_list.draft.json` 来审阅并接收该草稿，随后再锁 Gate C，避免必须先锁定才能批准草稿的循环。原片观察需要上述观察字段及 `contract_sha256/source_sha256`。这些指纹由 `show` 和实际文件获得，记录动作拒绝过期输入。

正式导出先进入 `pending_sequence_review`。导出器在实际渲染成功后写 `*.receipt.json`，将影片 hash 与每段的合同、采用素材、剪辑和音轨指纹绑定。候选写单独 `*.candidate.mp4`；可以用于审阅，但不会自动变正式批准。`not_in_edit/delivery_scope` 区分全部计划镜头与部分交付，不能把部分预览称作完整成片。

段落审阅输入包含 `sequence_id/reviewer/viewed_file/viewed_sha256/answers/verdict/notes/blind/sound_review/known_issues`。审阅者先在不读剧本的条件下看具体导出，再回答合同问题。通过需要实际导出记录、每题答案、声音审查以及无未解决问题；可记录 `fail/inconclusive`。修改画面、声音、速度、切点、合同或被观看文件，审核即失效。Gate F 检查这些证据，仍由人锁。

导演台提供 `GET /api/productions/{slug}/narrative-review` 和 `POST .../narrative-review/{design|observe|sequence}`；POST 与 CLI 共用记录动作。UI 的旧审片/混音入口在登记版明确拒绝，不读旧版结果。

## 帧的三种角色与节奏规则

设计首帧为 `planned_start`；新设计尾用 `--slot end` → `04-frames/.../SHxxx-end.jpg`。旧 `--slot last` 仍兼容，但角色是 `planned_end`。视频抽尾放到绑定视频目录的 `SHxxx-last.jpg`，标 `generated_end`，绑定视频和图像 hash，身份通过后才供同机位续用。旧无元数据帧保持 `unknown/legacy`，文件名不证明状态。换机位重新锚定；设计父图只锁人物和场景，本镜起点按 `in_from`。

SPM、长镜、复合动词、反应镜、景别变化属于创作提醒，不能按配额强制拆镜。非法时间、真实模型上限、缺合同/审核、素材变更和丢失核心事件仍阻断。影像省略是否有效由具体段落审阅判断。

## 《一瑞尔》现状和边界

本轮登记 `ep01/rhythm-v2`：53 镜、计划 111 秒；实际采用 51 镜，SH052/SH053 尚未生成。现有 smoothcut 报告转换成统一 EDL，保留原片区间、速度、音轨和实际帧时长；原报告、分镜、影片均保留。

抽取并查看 SH015 原片 1.3 秒的帧，铜钱明显发亮；现有剪辑只采用 0.1–0.6 秒。新检查返回 **fail，事件保留 0 秒**。其余事件及两段理解审核保持待审，没有推定观众已懂，也没有把 SH042 误判为同样丢失。

当前 `check_prod.py` 明确检查 53 镜版，并报告缺该版 writer 交接文件。此前临时生产表还缺新协议所需的标准交接/审核，不能继续借旧 28 镜版获得通过。后续迁移应补齐真实交接并重新审阅，不改几个 pass 字段蒙混过关。

本轮实现稳定的主路径和反例验证，不承诺模型或艺术判断“完美”。登记版旧 SFX 全原片串接入口已停用；新增 EDL 可采用实际声音区间，完整的音效/音乐床制作和 UI 交互仍可继续扩展。当前没有调用付费视频，没有重做吃粉段落。


## 最终验证记录

2026-10-06 全量离线回归 **457 项全部通过**（20.904 秒），编译和 `git diff --check` 通过。测试子进程移除真实凭据并禁止 socket/DNS 连接；生成器测试使用 mock，真实 FFmpeg 测试仅处理临时目录中的本地样片。结果见 [验证记录](pipeline-upgrade-validation-2026-10-06.json)。

生产回归报告：`productions/011-one-riel/.pipeline/narrative_upgrade_check.ep01-rhythm-v2.json`。本轮实际原片证据帧保存在 `08-qc/ep01-rhythm-v2/evidence/SH015-source-1.300.png`；它不是新资产或设计关键帧，不作为整段理解通过证据。
