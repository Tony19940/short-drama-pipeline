import { useEffect, useMemo, useState } from "react";
import { get, post, put } from "../api";

type Shot = Record<string, any>;
type Card = Record<string, any>;
type Grammar = Record<string, any>;
type SceneRow = Record<string, any>;
type FrameDesc = Record<string, any>;

const V2 = "shot-table-v2";
const COVERAGE = ["master", "otc", "reverse", "reaction", "insert", "empty", "continuous", "close", "single", "pov", "follow"];
const SCALES = ["wide", "full", "medium", "close", "otc", "insert", "pov"];
const ANGLES = ["eye", "high", "low"];
const MOVES = ["static", "push", "pull", "pan", "tilt", "track", "follow", "handheld", "crane"];
const DELIVERY = ["none", "post", "on_camera"];
const DIMS = ["reveal_order", "the_shot", "rhythm", "silence", "card_fit", "continuity", "model_risk"];

function txt(value: any, fallback = "—"): string {
  if (value === undefined || value === null || value === "") return fallback;
  if (Array.isArray(value)) return value.length ? value.map((v) => txt(v, "")).filter(Boolean).join("、") : fallback;
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function fmt(value: any): string {
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : String(Math.round(value * 100) / 100);
  return txt(value);
}

function yn(value: any): string {
  return value === true ? "是" : value === false ? "否" : "—";
}

function splitList(text: string): string[] {
  return text
    .split(/[、,，;；]/)
    .map((s) => s.trim())
    .filter(Boolean);
}

function ratio(aspect: any): string | undefined {
  const m = /^(\d+)\s*[:：xX]\s*(\d+)$/.exec(String(aspect || "").trim());
  return m ? `${m[1]} / ${m[2]}` : undefined;
}

function withOptions(list: string[], current: any): string[] {
  const value = txt(current, "");
  return value && !list.includes(value) ? [...list, value] : list;
}

function dialogueLine(item: any): string {
  if (!item) return "";
  if (typeof item === "string") return item;
  const who = txt(item.character, "");
  const line = txt(item.line, "");
  return who ? `${who}：${line}` : line;
}

function motifConstraint(m: Record<string, any>): string {
  const parts: string[] = [];
  if (Array.isArray(m.scale_not) && m.scale_not.length) parts.push(`不许 ${m.scale_not.join("/")}`);
  if (Array.isArray(m.scale_in) && m.scale_in.length) parts.push(`只许 ${m.scale_in.join("/")}`);
  if (m.angle) parts.push(String(m.angle));
  if (m.height) parts.push(`机高 ${m.height}`);
  return parts.join("；") || "—";
}

function motifWhen(m: Record<string, any>): string {
  const parts: string[] = [];
  if (m.when) parts.push(String(m.when));
  if (Array.isArray(m.scenes) && m.scenes.length) parts.push(m.scenes.join("、"));
  if (m.from_scene) parts.push(`自 ${m.from_scene}`);
  if (m.until_scene) parts.push(`到 ${m.until_scene}`);
  return parts.join(" · ") || "—";
}

function SceneCardBlock({ sceneId, card, shots }: { sceneId: string; card?: Card; shots: Shot[] }) {
  const secs = shots.reduce((sum, s) => sum + (Number(s.duration_sec) || 0), 0);
  return (
    <details className="soft">
      <summary>
        {sceneId} · 场卡
        {shots.length ? <span className="dim">　{shots.length} 镜 · {secs} 秒</span> : null}
      </summary>
      {card ? (
        <div>
          <p>戏剧问题：{txt(card.dramatic_question)}</p>
          <p>
            翻转点：{txt(card.turn?.at)}
            {card.turn?.what_flips ? `（${card.turn.what_flips}）` : ""}
          </p>
          <p>
            情绪曲线：{txt(card.emotion_curve?.start)} → {txt(card.emotion_curve?.peak)} → {txt(card.emotion_curve?.end)}
            {card.emotion_curve?.peak_at ? `，最高点 ${card.emotion_curve.peak_at}` : ""}
          </p>
          <p>
            那一颗：{txt(card.the_shot?.moment)}
            {card.the_shot?.scale ? `（${card.the_shot.scale}）` : ""}
            {card.the_shot?.why ? <span className="dim">　{card.the_shot.why}</span> : null}
          </p>
          <p>揭示顺序：{Array.isArray(card.reveal_order) && card.reveal_order.length ? card.reveal_order.join(" → ") : "—"}</p>
          <p className="dim">
            视点 {txt(card.pov)} · 距离策略 {txt(card.distance_strategy)} · 光的动机 {txt(card.light_motivation)}
            {card.color_shift ? ` · 色彩变化 ${txt(card.color_shift)}` : ""}
          </p>
          <p className="dim">静音测试：{txt(card.silence_test)}</p>
          <p className="dim">参考场型：{txt(card.case_cards)}</p>
        </div>
      ) : (
        <p className="dim">还没有场卡，先点场戏分析</p>
      )}
    </details>
  );
}

function GrammarBlock({ grammar }: { grammar: Grammar }) {
  const motifs: Record<string, any>[] = Array.isArray(grammar.motifs) ? grammar.motifs : [];
  const hook = grammar.ending_hook || {};
  return (
    <details className="soft">
      <summary>全集视觉语法</summary>
      <p className="dim">景别节奏：{txt(grammar.scale_rhythm)}</p>
      <p className="dim">光的动机：{txt(grammar.light_motivation)}</p>
      <p className="dim">色彩弧线：{txt(grammar.color_arc)}</p>
      <p className="dim">
        结尾钩子：{Array.isArray(hook.scale) && hook.scale.length ? hook.scale.join("/") : txt(hook.scale)}
        {hook.note ? `　${hook.note}` : ""}
      </p>
      {motifs.length ? (
        <table className="plain">
          <thead>
            <tr>
              <th>母题</th>
              <th>对象</th>
              <th>何时</th>
              <th>约束</th>
              <th>规则</th>
            </tr>
          </thead>
          <tbody>
            {motifs.map((m, i) => (
              <tr key={m.id || i}>
                <td>{txt(m.id)}</td>
                <td>{txt(m.subject)}</td>
                <td>{motifWhen(m)}</td>
                <td>{motifConstraint(m)}</td>
                <td>{txt(m.rule)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="dim">没有母题</p>
      )}
    </details>
  );
}

function CandidateBlock({
  sceneId,
  row,
  pick,
  busy,
  locked,
  onPick,
}: {
  sceneId: string;
  row: SceneRow;
  pick: number;
  busy: string;
  locked: boolean;
  onPick: (index: number) => void;
}) {
  const candidates: Record<string, any>[] = Array.isArray(row.candidates) ? row.candidates : [];
  const verdict = row.verdict || {};
  const scores: Record<string, any>[] = Array.isArray(verdict.scores) ? verdict.scores : [];
  const scoreOf = (i: number) => scores.find((s) => Number(s?.candidate) === i);
  const metric = (i: number) => (candidates[i]?.metrics || {}) as Record<string, any>;
  const rows: [string, (m: Record<string, any>) => string][] = [
    ["镜数", (m) => fmt(m.shots)],
    ["总秒", (m) => fmt(m.total_sec)],
    ["景别曲线", (m) => txt(m.scale_curve)],
    ["最紧", (m) => txt(m.tightest)],
    ["静止比", (m) => fmt(m.static_ratio)],
    ["对白后反应", (m) => fmt(m.reactions_after_dialogue)],
    ["那一颗落地", (m) => yn(m.the_shot_landed)],
    ["那一颗最紧", (m) => yn(m.the_shot_tightest)],
    ["警告数", (m) => fmt(m.warnings)],
  ];
  if (!candidates.length) return null;
  return (
    <details className="soft">
      <summary>
        {sceneId} · 候选 {candidates.length} 版
      </summary>
      <table className="plain">
        <thead>
          <tr>
            <th></th>
            {candidates.map((c, i) => (
              <th key={i}>
                {i === pick ? "★ " : ""}
                {i + 1} {txt(c.label || c.style, "")}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, cell]) => (
            <tr key={label}>
              <td className="dim">{label}</td>
              {candidates.map((_, i) => (
                <td key={i}>{cell(metric(i))}</td>
              ))}
            </tr>
          ))}
          {DIMS.map((key) => (
            <tr key={key}>
              <td className="dim">评审·{key}</td>
              {candidates.map((_, i) => (
                <td key={i}>{fmt(scoreOf(i)?.dims?.[key])}</td>
              ))}
            </tr>
          ))}
          <tr>
            <td className="dim">评审·总分</td>
            {candidates.map((_, i) => (
              <td key={i}>
                <b>{fmt(scoreOf(i)?.total)}</b>
              </td>
            ))}
          </tr>
        </tbody>
      </table>
      {verdict.why ? (
        <p>
          评审选第 {Number(verdict.pick ?? pick) + 1} 版（{txt(verdict.source, "?")}）：{verdict.why}
        </p>
      ) : null}
      {verdict.merge ? <p className="dim">合并建议：{verdict.merge}</p> : null}
      {candidates.map((c, i) => {
        const s = scoreOf(i);
        const notes = txt(s?.notes, "");
        const fixes: string[] = Array.isArray(s?.fixes) ? s?.fixes : [];
        const warnings: string[] = Array.isArray(c.warnings) ? c.warnings : [];
        if (!notes && !fixes.length && !warnings.length) return null;
        return (
          <p key={i} className="dim">
            第 {i + 1} 版：{notes}
            {fixes.length ? `　修法：${fixes.join("；")}` : ""}
            {warnings.length ? `　警告：${warnings.join("；")}` : ""}
          </p>
        );
      })}
      <div className="toolbar">
        {candidates.map((_, i) => {
          const key = `pick:${sceneId}:${i}`;
          return (
            <button key={i} className="ghost compact" disabled={i === pick || !!busy || locked} onClick={() => onPick(i)}>
              {busy === key ? "改选中…" : i === pick ? `第 ${i + 1} 版 · 当前` : `选这版 ${i + 1}`}
            </button>
          );
        })}
        {locked ? <span className="dim">正式表不是 shot-table-v2，不能改选</span> : null}
      </div>
    </details>
  );
}

export function ShotTablePage({ slug, onChanged }: { slug: string; onChanged: () => void }) {
  const [table, setTable] = useState<any>(null);
  const [cards, setCards] = useState<any>({});
  const [frameDesc, setFrameDesc] = useState<any>({});
  const [candidates, setCandidates] = useState<any>({ scenes: [], picks: {} });
  const [animatic, setAnimatic] = useState<any>(null);
  const [built, setBuilt] = useState<any>(null);
  const [builtAt, setBuiltAt] = useState(0);
  const [selected, setSelected] = useState(0);
  const [draft, setDraft] = useState<Shot | null>(null);
  const [sfxText, setSfxText] = useState("");
  const [count, setCount] = useState(3);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [note, setNote] = useState("");

  async function load() {
    const [t, c, f, d, a] = await Promise.all([
      get(`/api/productions/${slug}/pipeline/shot_list.json`).catch(() => ({})),
      get(`/api/productions/${slug}/pipeline/scene_cards.json`).catch(() => ({})),
      get(`/api/productions/${slug}/pipeline/frame_descriptions.json`).catch(() => ({})),
      get(`/api/productions/${slug}/design/candidates`).catch(() => ({ scenes: [], picks: {} })),
      get(`/api/productions/${slug}/animatic?episode=1`).catch(() => null),
    ]);
    setTable(t && typeof t === "object" ? t : {});
    setCards(c && typeof c === "object" ? c : {});
    setFrameDesc(f && typeof f === "object" ? f : {});
    setCandidates(d && typeof d === "object" ? d : { scenes: [], picks: {} });
    setAnimatic(a);
  }

  useEffect(() => {
    setSelected(0);
    setDraft(null);
    setSfxText("");
    setBuilt(null);
    setBuiltAt(0);
    setError("");
    setNote("");
    setTable(null);
    load().catch((err: any) => setError(err.message));
  }, [slug]);

  const isV2 = table?.schema === V2;
  const shots: Shot[] = useMemo(() => (Array.isArray(table?.shots) ? table.shots : []), [table]);
  const sceneCards: Card[] = useMemo(() => {
    if (Array.isArray(cards?.scene_cards) && cards.scene_cards.length) return cards.scene_cards;
    return Array.isArray(table?.scene_cards) ? table.scene_cards : [];
  }, [cards, table]);
  const grammar: Grammar | null = cards?.visual_grammar || table?.visual_grammar || null;
  const cardById = useMemo(() => {
    const map: Record<string, Card> = {};
    sceneCards.forEach((c) => {
      if (c?.scene_id) map[String(c.scene_id)] = c;
    });
    return map;
  }, [sceneCards]);
  const descById = useMemo(() => {
    const map: Record<string, FrameDesc> = {};
    (Array.isArray(frameDesc?.items) ? frameDesc.items : []).forEach((item: any) => {
      if (item?.shot_id) map[String(item.shot_id)] = item;
    });
    return map;
  }, [frameDesc]);
  const candByScene = useMemo(() => {
    const map: Record<string, SceneRow> = {};
    (Array.isArray(candidates?.scenes) ? candidates.scenes : []).forEach((row: any) => {
      if (row?.scene_id) map[String(row.scene_id)] = row;
    });
    return map;
  }, [candidates]);
  const byScene = useMemo(() => {
    const order: string[] = [];
    const map: Record<string, Shot[]> = {};
    const add = (sid: string) => {
      if (!sid) return;
      if (!map[sid]) {
        map[sid] = [];
        order.push(sid);
      }
    };
    shots.forEach((s) => {
      const sid = String(s.scene_id || table?.scene_id || "EP01");
      add(sid);
      map[sid].push(s);
    });
    sceneCards.forEach((c) => add(String(c?.scene_id || "")));
    Object.keys(candByScene).forEach((sid) => add(sid));
    return order.map((sid) => ({ scene_id: sid, shots: map[sid] }));
  }, [shots, sceneCards, candByScene, table]);

  const sel = shots.length ? Math.min(selected, shots.length - 1) : 0;
  const base: Shot | undefined = shots[sel];
  const shot: Shot | undefined = draft || base;
  const frames: Record<string, string> = animatic?.frames || {};
  const lastFrames: Record<string, string> = animatic?.last_frames || {};
  const thumbRatio = ratio(table?.aspect);
  const videoUrl: string = built?.url || (animatic?.exists ? animatic.url : "") || "";
  // cache-bust only after a rebuild in this session, so the <video> refetches the new file
  const videoSrc = videoUrl && builtAt ? `${videoUrl}${videoUrl.includes("?") ? "&" : "?"}t=${builtAt}` : videoUrl;
  const warnings: string[] = Array.isArray(table?.warnings) ? table.warnings : [];
  const desc: FrameDesc | undefined = shot ? descById[String(shot.shot_id)] : undefined;

  function pickOf(sceneId: string, row?: SceneRow): number {
    const fromRow = row?.pick;
    const fromTable = table?.candidate_picks?.[sceneId];
    const fromRoot = candidates?.picks?.[sceneId];
    const v = fromRow ?? fromTable ?? fromRoot ?? 0;
    return Number.isFinite(Number(v)) ? Number(v) : 0;
  }

  function select(index: number) {
    setSelected(index);
    setDraft(null);
    setSfxText(txt(shots[index]?.key_sfx, ""));
    setError("");
    setNote("");
  }

  // First edit opens a draft cloned from the saved shot; the sfx text box is seeded at the same moment
  // so a save that never touched key_sfx still writes the original list back.
  function begin(): Shot | null {
    if (!base) return null;
    if (!draft) setSfxText(txt(base.key_sfx, ""));
    return structuredClone(draft || base);
  }

  function edit(key: string, value: any) {
    const current = begin();
    if (!current) return;
    current[key] = value;
    setDraft(current);
  }

  function editNumber(key: string, value: string) {
    const current = begin();
    if (!current) return;
    if (value === "") {
      if (key === "emotion_level") delete current[key];
      else current[key] = 0;
    } else {
      const n = Number(value);
      current[key] = key === "emotion_level" ? Math.max(0, Math.min(10, n)) : n;
    }
    setDraft(current);
  }

  function editState(noteText: string) {
    const current = begin();
    if (!current) return;
    current.state = { ...(current.state || {}), note: noteText };
    setDraft(current);
  }

  function editSfx(text: string) {
    if (!base) return;
    setSfxText(text);
    if (!draft) setDraft(structuredClone(base));
  }

  async function reload() {
    await load();
    onChanged();
  }

  async function runAgent(station: string, body: Record<string, unknown>) {
    setBusy(station);
    setError("");
    setNote("");
    try {
      const result = await post(`/api/productions/${slug}/agents/${station}`, body);
      setNote(result?.note || (result?.used_tokens ? "已起草，还没锁定。" : "已完成"));
      setDraft(null);
      await reload();
    } catch (err: any) {
      setError(err.message || String(err));
    } finally {
      setBusy("");
    }
  }

  async function buildAnimatic() {
    setBusy("animatic");
    setError("");
    setNote("");
    try {
      const result = await post(`/api/productions/${slug}/animatic`, { episode: 1 });
      setBuilt(result);
      setBuiltAt(Date.now());
      await reload();
    } catch (err: any) {
      setError(err.message || String(err));
    } finally {
      setBusy("");
    }
  }

  async function pickCandidate(sceneId: string, index: number) {
    setBusy(`pick:${sceneId}:${index}`);
    setError("");
    setNote("");
    try {
      await post(`/api/productions/${slug}/design/pick`, { scene_id: sceneId, candidate: index });
      setNote(`${sceneId} 改选第 ${index + 1} 版，表已重排`);
      setDraft(null);
      await reload();
    } catch (err: any) {
      setError(err.message || String(err));
    } finally {
      setBusy("");
    }
  }

  async function saveShot() {
    if (!table || !isV2 || !draft || !base) return;
    setBusy("save");
    setError("");
    setNote("");
    try {
      const next = structuredClone(table);
      next.shots[sel] = { ...draft, key_sfx: splitList(sfxText) };
      await put(`/api/productions/${slug}/pipeline/shot_list.json`, next);
      setNote("已保存，机器校验已过");
      setDraft(null);
      await reload();
    } catch (err: any) {
      setError(err.message || String(err));
    } finally {
      setBusy("");
    }
  }

  if (table === null && !error) return <p className="dim">读取镜头表…</p>;

  const noFfmpeg = animatic?.ffmpeg === false;
  const picksLine = table?.candidate_picks && typeof table.candidate_picks === "object"
    ? Object.entries(table.candidate_picks as Record<string, any>)
        .map(([sid, idx]) => `${sid} 选第 ${Number(idx) + 1} 版`)
        .join("；")
    : "";

  const toolbar = (
    <div className="toolbar">
      <button className="ghost" disabled={!!busy} onClick={() => runAgent("analysis", {})}>
        {busy === "analysis" ? "场戏分析…工作中" : "场戏分析"}
      </button>
      <button className="danger" disabled={!!busy} onClick={() => runAgent("design", { candidates: count })}>
        {busy === "design" ? "导演 Agent 拆镜…工作中" : `导演 Agent 拆镜（${count} 版）`}
      </button>
      <select value={count} onChange={(e) => setCount(Number(e.target.value))} disabled={!!busy}>
        <option value={1}>1 版</option>
        <option value={2}>2 版</option>
        <option value={3}>3 版</option>
      </select>
      <button className="ghost" disabled={!!busy || !shots.length} onClick={() => runAgent("frame_desc", {})}>
        {busy === "frame_desc" ? "画面描述…工作中" : "画面描述"}
      </button>
      <button className="ghost" disabled={!!busy || noFfmpeg || !shots.length} onClick={buildAnimatic}>
        {busy === "animatic" ? "静帧 animatic…工作中" : "静帧 animatic"}
      </button>
      {noFfmpeg ? <span className="warn">本机没有 ffmpeg</span> : null}
      <span className="dim">每场拆 {count} 版，评审 Agent 挑一版，人可改选。没有密钥不会装懂。</span>
    </div>
  );

  const messages = (
    <>
      {error ? <p className="err">{error}</p> : null}
      {note ? <p className="ok">{note}</p> : null}
      {built ? (
        <p className={built.missing?.length ? "warn" : "dim"}>
          animatic {fmt(built.total_sec)} 秒 · {fmt(built.cards)} 卡
          {built.missing?.length ? ` · 缺首帧 ${built.missing.join(", ")}` : ""}
        </p>
      ) : null}
    </>
  );

  const sceneBlocks = (
    <>
      {grammar ? <GrammarBlock grammar={grammar} /> : null}
      {byScene.map(({ scene_id, shots: sceneShots }) => {
        const row = candByScene[scene_id];
        return (
          <div key={scene_id}>
            <SceneCardBlock sceneId={scene_id} card={cardById[scene_id]} shots={sceneShots} />
            {row ? (
              <CandidateBlock
                sceneId={scene_id}
                row={row}
                pick={pickOf(scene_id, row)}
                busy={busy}
                locked={!isV2}
                onPick={(i) => pickCandidate(scene_id, i)}
              />
            ) : null}
          </div>
        );
      })}
    </>
  );

  if (!shots.length) {
    return (
      <div>
        {toolbar}
        <p className="warn">还没有镜头表。先「场戏分析」，再「导演 Agent 拆镜」。</p>
        {messages}
        {sceneBlocks}
      </div>
    );
  }

  const thumb = shot ? frames[String(shot.shot_id)] : "";
  const prevSame = (() => {
    if (!shot) return undefined;
    for (let i = sel - 1; i >= 0; i -= 1) {
      if (String(shots[i].scene_id || "") === String(shot.scene_id || "")) return shots[i];
    }
    return undefined;
  })();
  const prevLast = prevSame ? lastFrames[String(prevSame.shot_id)] : "";

  return (
    <div>
      {toolbar}
      <p className="dim">
        {shots.length} 镜 · {fmt(table?.total_sec)} 秒 · 画幅 {txt(table?.aspect)} · 视点 {txt(table?.whose_pov)} · 模型 {txt(table?.target_model)} · 状态 {txt(table?.status)}
      </p>
      {picksLine ? <p className="dim">候选：{picksLine}</p> : null}
      {!isV2 ? <p className="warn">这张表是从旧 shots.json 编译的，不是 shot-table-v2；点「导演 Agent 拆镜」生成正式表</p> : null}
      {messages}
      {sceneBlocks}
      <div className="strip">
        {shots.map((item, index) => {
          const url = frames[String(item.shot_id)];
          return (
            <button key={item.shot_id || index} className={`strip-card shot-card ${index === sel ? "on" : ""}`} onClick={() => select(index)}>
              {url ? <img src={url} alt="" style={thumbRatio ? { aspectRatio: thumbRatio } : undefined} /> : <div className="thumb" style={thumbRatio ? { aspectRatio: thumbRatio } : undefined} />}
              <div>
                <b>{item.shot_id}</b>
                <div className="dim">
                  {txt(item.duration_sec, "?")}s · {txt(item.coverage_type)} · {txt(item.scale)} · {txt(item.lens)}
                </div>
                <div className="dim">
                  {txt(item.move_type || item.move_needed)}
                  {item.move_reason ? `：${item.move_reason}` : ""}
                </div>
                <div>
                  左 {item.left || "—"} / 右 {item.right || "—"}
                </div>
                <div>
                  {item.emotion_level !== undefined && item.emotion_level !== null ? <span className="tag">情绪 {item.emotion_level}</span> : null}
                  {item.hardest ? <span className="tag hot">最难</span> : null}
                  {item.visual_turn ? <span className="tag">视觉转折</span> : null}
                  {item.camera_id ? <span className="tag">机位 {item.camera_id}</span> : null}
                </div>
              </div>
            </button>
          );
        })}
      </div>
      <div className="desk">
        <section className="desk-spec">
          {shot ? (
            <>
              <h2>
                {shot.shot_id} · {sel + 1}/{shots.length}
                {shot.scene_id ? <span className="dim">　{shot.scene_id}</span> : null}
              </h2>
              {isV2 ? (
                <>
                  <label>
                    节拍 beat
                    <input value={shot.beat || ""} onChange={(e) => edit("beat", e.target.value)} />
                  </label>
                  <label>
                    这一镜干什么 shot_job
                    <input value={shot.shot_job || ""} onChange={(e) => edit("shot_job", e.target.value)} />
                  </label>
                  <div className="grid cols-3">
                    <label>
                      覆盖类型
                      <select value={shot.coverage_type || "master"} onChange={(e) => edit("coverage_type", e.target.value)}>
                        {withOptions(COVERAGE, shot.coverage_type).map((v) => (
                          <option key={v} value={v}>
                            {v}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      景别
                      <select value={shot.scale || "medium"} onChange={(e) => edit("scale", e.target.value)}>
                        {withOptions(SCALES, shot.scale).map((v) => (
                          <option key={v} value={v}>
                            {v}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      角度
                      <select value={shot.angle || "eye"} onChange={(e) => edit("angle", e.target.value)}>
                        {withOptions(ANGLES, shot.angle).map((v) => (
                          <option key={v} value={v}>
                            {v}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      机高
                      <input value={shot.height || ""} onChange={(e) => edit("height", e.target.value)} />
                    </label>
                    <label>
                      焦段
                      <input value={shot.lens || ""} onChange={(e) => edit("lens", e.target.value)} placeholder="35mm" />
                    </label>
                    <label>
                      机位 camera_id
                      <input value={shot.camera_id || ""} onChange={(e) => edit("camera_id", e.target.value)} />
                    </label>
                  </div>
                  <div className="grid cols-2">
                    <label>
                      运镜
                      <select value={shot.move_type || "static"} onChange={(e) => edit("move_type", e.target.value)}>
                        {withOptions(MOVES, shot.move_type).map((v) => (
                          <option key={v} value={v}>
                            {v}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      为什么要动
                      <input value={shot.move_reason || ""} onChange={(e) => edit("move_reason", e.target.value)} />
                    </label>
                    <label>
                      左
                      <input value={shot.left || ""} onChange={(e) => edit("left", e.target.value)} />
                    </label>
                    <label>
                      右
                      <input value={shot.right || ""} onChange={(e) => edit("right", e.target.value)} />
                    </label>
                    <label>
                      视线
                      <input value={shot.eyeline || ""} onChange={(e) => edit("eyeline", e.target.value)} />
                    </label>
                    <label>
                      对白方式
                      <select value={shot.dialogue_delivery || "none"} onChange={(e) => edit("dialogue_delivery", e.target.value)}>
                        {withOptions(DELIVERY, shot.dialogue_delivery).map((v) => (
                          <option key={v} value={v}>
                            {v}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                  <label>
                    这一镜只做一件事 one_action
                    <textarea className="short" value={shot.one_action || ""} onChange={(e) => edit("one_action", e.target.value)} />
                  </label>
                  <div className="grid cols-3">
                    <label>
                      时长秒
                      <input type="number" min={0} step={1} value={shot.duration_sec ?? ""} onChange={(e) => editNumber("duration_sec", e.target.value)} />
                    </label>
                    <label>
                      情绪 0–10<span className="hint">留空则不填</span>
                      <input type="number" min={0} max={10} step={1} value={shot.emotion_level ?? ""} onChange={(e) => editNumber("emotion_level", e.target.value)} />
                    </label>
                    <label>
                      关键音效<span className="hint">顿号分隔</span>
                      <input value={draft ? sfxText : txt(shot.key_sfx, "")} onChange={(e) => editSfx(e.target.value)} />
                    </label>
                    <label>
                      从哪接进 in_from
                      <input value={shot.in_from || ""} onChange={(e) => edit("in_from", e.target.value)} />
                    </label>
                    <label>
                      接到哪去 out_to
                      <input value={shot.out_to || ""} onChange={(e) => edit("out_to", e.target.value)} />
                    </label>
                    <div>
                      <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
                        <input type="checkbox" style={{ width: "auto" }} checked={!!shot.visual_turn} onChange={(e) => edit("visual_turn", e.target.checked)} />
                        视觉转折
                      </label>
                      <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
                        <input type="checkbox" style={{ width: "auto" }} checked={!!shot.hardest} onChange={(e) => edit("hardest", e.target.checked)} />
                        最难的一镜
                      </label>
                    </div>
                  </div>
                  {shot.state && typeof shot.state === "object" ? (
                    <label>
                      连戏句 state.note
                      <textarea className="short" value={shot.state.note || ""} onChange={(e) => editState(e.target.value)} />
                    </label>
                  ) : null}
                  {Array.isArray(shot.state_changes) && shot.state_changes.length ? <p className="dim">状态变化：{shot.state_changes.join("；")}</p> : null}
                  <p className="dim">
                    台词（编剧原句，只读）：
                    {Array.isArray(shot.dialogue_ref) && shot.dialogue_ref.length ? shot.dialogue_ref.map(dialogueLine).filter(Boolean).join(" / ") : "无"}
                  </p>
                  {shot.light && typeof shot.light === "object" ? (
                    <p className="dim">
                      光：{txt(shot.light.day_night, "")} {txt(shot.light.key_dir, "")} {txt(shot.light.quality, "")} {txt(shot.light.color, "")}
                    </p>
                  ) : null}
                  {Array.isArray(shot.evidence) && shot.evidence.length ? <p className="dim">证据：{shot.evidence.join("；")}</p> : null}
                  <div className="toolbar">
                    <button className="danger" disabled={!draft || busy === "save"} onClick={saveShot}>
                      {busy === "save" ? "保存中…" : "保存这一镜"}
                    </button>
                    {draft ? (
                      <button className="ghost" disabled={busy === "save"} onClick={() => select(sel)}>
                        放弃改动
                      </button>
                    ) : null}
                  </div>
                  {error ? <p className="err">{error}</p> : null}
                  {note ? <p className="ok">{note}</p> : null}
                </>
              ) : (
                <>
                  <p>节拍：{txt(shot.beat)}</p>
                  <p>这一镜干什么：{txt(shot.shot_job)}</p>
                  <p className="dim">
                    覆盖 {txt(shot.coverage_type)} · {txt(shot.move_needed)}
                    {shot.move_reason ? `：${shot.move_reason}` : ""}
                  </p>
                  <p className="dim">
                    台词：{Array.isArray(shot.dialogue_ref) && shot.dialogue_ref.length ? shot.dialogue_ref.map(dialogueLine).filter(Boolean).join(" / ") : "无"}
                  </p>
                  <p className="dim">旧表编译，不能在这里改；生成正式表后再编辑</p>
                </>
              )}
              <details className="soft" open>
                <summary>画面描述</summary>
                {desc ? (
                  <>
                    <p>{txt(desc.one_paragraph, "")}</p>
                    <p className="dim">
                      前景 {txt(desc.layers?.foreground)} / 中景 {txt(desc.layers?.midground)} / 背景 {txt(desc.layers?.background)}
                    </p>
                    <p className="dim">
                      光：主 {txt(desc.light?.key)} 补 {txt(desc.light?.fill)}
                      {desc.light?.practical ? ` 实用光 ${desc.light.practical}` : ""}
                      {desc.light?.quality ? ` 质感 ${desc.light.quality}` : ""}
                    </p>
                    <p className="dim">
                      手：{txt(desc.subject?.hands)}
                      {desc.subject?.holding ? ` · 拿着 ${desc.subject.holding}` : ""}
                      {desc.subject?.facing ? ` · 面向 ${desc.subject.facing}` : ""}
                      {desc.subject?.micro_expression ? ` · 微表情 ${desc.subject.micro_expression}` : ""}
                    </p>
                    <p className="dim">
                      构图：重心 {txt(desc.composition?.weight)} · 留白 {txt(desc.composition?.negative_space)} · 头顶 {txt(desc.composition?.headroom)}
                      {desc.height_meaning ? ` · 机高含义 ${desc.height_meaning}` : ""}
                    </p>
                    {Array.isArray(desc.forbidden) && desc.forbidden.length ? <p className="warn">禁止：{desc.forbidden.join("；")}</p> : null}
                  </>
                ) : (
                  <p className="dim">还没有画面描述，点「画面描述」生成</p>
                )}
              </details>
            </>
          ) : null}
        </section>
        <aside>
          {thumb ? <img src={thumb} alt="" /> : <p className="dim">还没有首帧</p>}
          {prevLast && thumb ? (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginTop: 8 }}>
              <div>
                <img src={prevLast} alt="" />
                <p className="dim">上镜尾 {txt(prevSame?.shot_id)}</p>
              </div>
              <div>
                <img src={thumb} alt="" />
                <p className="dim">本镜首 {txt(shot?.shot_id)}</p>
              </div>
              <p className="dim" style={{ gridColumn: "1 / -1" }}>
                {txt(prevSame?.out_to)} → {txt(shot?.in_from)}
              </p>
            </div>
          ) : null}
          {videoUrl ? (
            <details className="soft" open>
              <summary>静帧 animatic</summary>
              <video key={videoSrc} src={videoSrc} controls style={{ width: "100%", background: "#000" }} />
              <p className="dim">
                {fmt(built?.total_sec ?? animatic?.total_sec)} 秒 · {fmt(built?.cards ?? animatic?.cards)} 卡
              </p>
            </details>
          ) : null}
          {animatic?.missing?.length ? <p className="warn">缺首帧：{animatic.missing.join(", ")}</p> : null}
          <details className="soft" open={warnings.length > 0}>
            <summary>警告 {warnings.length}</summary>
            {warnings.length ? (
              <ul>
                {warnings.map((w, i) => (
                  <li key={i} className="warn">
                    {w}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="dim">没有警告</p>
            )}
          </details>
        </aside>
      </div>
    </div>
  );
}
