import { useEffect, useMemo, useState } from "react";
import { get, post, put } from "../api";

const RUNTIME_KEYS = new Set([
  "parent",
  "frame_exists",
  "frame_url",
  "video_exists",
  "video_url",
  "last_exists",
  "last_url",
  "i2v",
  "refs",
  "missing_sheets",
  "compiled_prompt",
  "compiled_h3",
  "video_mode",
  "end",
]);

function contractPayload(board: any) {
  return {
    episode: board.episode,
    kind: board.kind,
    aspect: board.aspect,
    shots: board.shots.map((shot: any) => {
      const next: Record<string, unknown> = {};
      Object.entries(shot).forEach(([key, value]) => {
        if (!RUNTIME_KEYS.has(key)) next[key] = value;
      });
      return next;
    }),
  };
}

export function ShotsPage({ slug, onChanged }: { slug: string; onChanged: () => void }) {
  const [bible, setBible] = useState("");
  const [board, setBoard] = useState<any>(null);
  const [selected, setSelected] = useState(0);
  const [error, setError] = useState("");
  const [check, setCheck] = useState("");
  const [task, setTask] = useState<any>(null);
  const [inbox, setInbox] = useState<any>(null);
  const [busy, setBusy] = useState("");
  const [rev, setRev] = useState(0);
  const [draft, setDraft] = useState<any>(null);
  const [incomingDraft, setIncomingDraft] = useState<any>(null);
  const [useDraft, setUseDraft] = useState(false);
  const [review, setReview] = useState<any>(null);
  const [grid, setGrid] = useState<any>(null);

  async function load() {
    const [script, shots, box, incoming, existingReview, gridBoard] = await Promise.all([
      get(`/api/productions/${slug}/bible`),
      get(`/api/productions/${slug}/shots`),
      get(`/api/productions/${slug}/inbox`).catch(() => ({ tasks: [] })),
      get(`/api/productions/${slug}/shots/draft`).catch(() => ({ shots: [] })),
      get(`/api/productions/${slug}/review-draft`).catch(() => ({ exists: false, markdown: "" })),
      get(`/api/productions/${slug}/grid?source=official`).catch(() => ({ cells: [] })),
    ]);
    setBible(script.files?.["01-bible/ep01.md"] || "");
    setBoard(shots);
    setInbox(box);
    setIncomingDraft(incoming);
    setReview(existingReview);
    setGrid(gridBoard);
    setDraft(null);
    const officialCount = shots?.shots?.length || 0;
    const draftCount = incoming?.shots?.length || 0;
    if (draftCount > officialCount) setUseDraft(true);
    setRev((n) => n + 1);
  }

  useEffect(() => {
    load().catch((err) => setError(err.message));
  }, [slug]);

  useEffect(() => {
    const source = useDraft ? "draft" : "official";
    get(`/api/productions/${slug}/grid?source=${source}`)
      .then(setGrid)
      .catch(() => undefined);
  }, [slug, useDraft, rev]);

  const visible = useDraft ? incomingDraft : board;
  const shot = draft || visible?.shots?.[selected];
  const missing = useMemo(() => (shot?.missing_sheets || []) as string[], [shot]);

  async function persist(nextBoard = visible) {
    if (useDraft) {
      await put(`/api/productions/${slug}/shots/draft`, contractPayload(nextBoard));
      setCheck("草稿已保存，尚未覆盖正式 shots.json");
      await load();
      onChanged();
      return;
    }
    const result = await put(`/api/productions/${slug}/shots`, contractPayload(nextBoard));
    setCheck(result.check?.ok ? result.check.stdout : result.check?.stderr || result.check?.stdout);
    await load();
    onChanged();
  }

  function editShot(key: string, value: string | number) {
    if (!visible) return;
    const current = structuredClone(draft || visible.shots[selected]);
    current[key] = key === "seconds" ? Number(value) : value;
    setDraft(current);
  }

  async function patchShot() {
    if (!visible || !draft) return;
    setError("");
    const next = structuredClone(visible);
    next.shots[selected] = { ...next.shots[selected], ...draft };
    if (useDraft) setIncomingDraft(next);
    else setBoard(next);
    try {
      await persist(next);
    } catch (err: any) {
      setError(err.message);
      await load();
    }
  }

  async function acceptDraft() {
    setBusy("accept");
    setError("");
    try {
      const result = await post(`/api/productions/${slug}/shots/draft/accept`, {});
      setCheck(result.check?.ok ? result.check.stdout : "已接受草稿");
      setUseDraft(false);
      await load();
      onChanged();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function reviewDraft() {
    setBusy("review");
    setError("");
    try {
      const result = await post(`/api/productions/${slug}/review-draft`, {
        source: useDraft ? "draft" : "official",
      });
      setReview(result);
      setCheck(`审查 ${result.verdict} · 不改 shots.json`);
    } catch (err: any) {
      setError(err.message);
   } finally {
     setBusy("");
   }
 }

  async function runBreakdown() {
    setBusy("break");
    setError("");
    try {
      const result = await post(`/api/productions/${slug}/breakdown`, {});
      setUseDraft(true);
      setCheck("拆镜草稿 " + (result.shot_count || 0) + " 镜 · " + (result.origin || "director-breakdown"));
      await load();
      onChanged();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

 async function writeTask() {
   if (!shot) return;
    setBusy("task");
    setError("");
    try {
      const created = await post(`/api/productions/${slug}/inbox/task`, { shotId: shot.id });
      setTask(created);
      await navigator.clipboard.writeText(created.prompt || "");
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function scanDrop() {
    setBusy("scan");
    setError("");
    try {
      const result = await post(`/api/productions/${slug}/inbox/scan`, {});
      setInbox(result);
      await load();
      onChanged();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

 if (!board && !incomingDraft) return <p className="dim">读取分镜…</p>;

 return (
   <div>
      <div className="toolbar">
        <button className="danger" onClick={runBreakdown} disabled={busy === "break"}>
          {busy === "break" ? "导演 Agent 工作中…" : "让导演 Agent 拆镜"}
        </button>
        <span className="dim">有密钥时导演 Agent 读剧本拆镜；没有密钥只会用规则编译器，并明说。</span>
      </div>
      {(visible?.scenes || []).length ? (
        <div className="strip">
          {(visible.scenes || []).map((scene: any) => (
            <div key={scene.id} className="strip-card">
              <div>
                <b>{scene.id}</b>
                <div className="dim">{scene.case} · {(scene.rigs || []).map((rig: any) => rig.setup).join(" / ")}</div>
              </div>
            </div>
          ))}
        </div>
      ) : null}
     <div className="strip">
        {(visible?.shots || []).map((item: any, index: number) => (
          <button
            key={item.id}
            className={`strip-card ${index === selected ? "on" : ""}`}
            onClick={() => {
              setSelected(index);
              setDraft(null);
            }}
          >
           {item.frame_url ? <img src={item.frame_url} alt="" /> : item.source_frame_url ? <img src={item.source_frame_url} alt="" /> : <div className="thumb" />}
           <div>
             <b>{item.id}</b>
              <div className="dim">{item.seconds}s · {item.setup} · {item.move}{item.rig_id ? " · " + String(item.rig_id).split(":").pop() : ""}</div>
              <div className="dim">{item.line_kind || "narration"}{item.handle ? " · 手柄" + item.handle + "s" : ""}</div>
           </div>
          </button>
        ))}
      </div>
      {useDraft ? <p className="warn">现在改的是草稿，不会覆盖正式分镜。</p> : null}
      {error ? <p className="err">{error}</p> : null}
      {check ? <p className={check.includes("ok") ? "ok" : "dim"}>{check}</p> : null}
      {grid?.cells?.length ? (
        <details className="soft" open>
          <summary>整场宫格（只给人看，不拿去出片）</summary>
          <p className="dim">{grid.note}</p>
          {grid.warnings?.length ? <p className="warn">{grid.warnings.join("；")}</p> : null}
          <div className="strip">
            {grid.cells.map((cell: any) => (
              <div key={cell.id} className="strip-card">
                {cell.url ? <img src={cell.url} alt="" /> : <div className="thumb" />}
                <div>
                  <b>{cell.id}</b>
                  <div className="dim">{cell.setup} · {cell.move}</div>
                </div>
              </div>
            ))}
          </div>
        </details>
      ) : null}
      {incomingDraft?.shots?.length ? (
        <div className="toolbar">
          <button className={`pill ${useDraft ? "on" : ""}`} onClick={() => { setUseDraft(true); setDraft(null); }}>
            看草稿
          </button>
          <button className={`pill ${!useDraft ? "on" : ""}`} onClick={() => { setUseDraft(false); setDraft(null); }}>
            看正式表
          </button>
          <button className="danger" onClick={acceptDraft} disabled={busy === "accept"}>
            {busy === "accept" ? "接受中…" : "接受草稿为正式表"}
          </button>
        </div>
      ) : null}
      <div className="desk">
        <section className="desk-spec" key={`${shot?.id || "empty"}-${rev}`}>
          {shot ? (
            <>
              <h2>
                {shot.id} · {(selected || 0) + 1}/{(visible?.shots || []).length}
              </h2>
              {missing.length ? (
                <p className="warn">缺联络板：{missing.join(", ")}。新首帧还不能锁。</p>
              ) : (
                <p className="ok">联络板齐</p>
              )}
              <div className="grid cols-2">
                <label>景别<input value={shot.setup || ""} onChange={(e) => editShot("setup", e.target.value)} /></label>
                <label>运镜<input value={shot.move || ""} onChange={(e) => editShot("move", e.target.value)} /></label>
                <label>焦段<input value={shot.lens || ""} onChange={(e) => editShot("lens", e.target.value)} /></label>
                <label>轴线<input value={shot.axis || ""} onChange={(e) => editShot("axis", e.target.value)} /></label>
              </div>
              <label>第 0 秒站位<textarea className="short" value={shot.start || ""} onChange={(e) => editShot("start", e.target.value)} /></label>
              <p className="dim">续镜第 0 秒必须已经在动作中间，不要站好再开始。</p>
              <label>这一镜动作<textarea className="short" value={shot.action || ""} onChange={(e) => editShot("action", e.target.value)} /></label>
              <label>给模型的画面句<textarea value={shot.video_prompt || ""} onChange={(e) => editShot("video_prompt", e.target.value)} /></label>
              <div className="grid cols-2">
                <label>声音种类
                  <select value={shot.line_kind || "narration"} onChange={(e) => editShot("line_kind", e.target.value)}>
                    <option value="intro">出场简介</option>
                    <option value="dialogue">口述台词</option>
                    <option value="inner">心里台词</option>
                    <option value="narration">旁白</option>
                    <option value="sms">短信/字卡</option>
                    <option value="reaction">无台词反应</option>
                  </select>
                </label>
                <label>说话人<input value={shot.speaker || ""} onChange={(e) => editShot("speaker", e.target.value)} placeholder="口述/心里才填角色" /></label>
              </div>
              <label>工作轨台词<input value={shot.line || ""} onChange={(e) => editShot("line", e.target.value)} /></label>
              <label>后期字幕<input value={shot.caption || ""} onChange={(e) => editShot("caption", e.target.value)} /></label>
              <div className="toolbar">
                <button className="danger" onClick={patchShot} disabled={!draft}>保存这一镜</button>
              </div>
              <details className="soft">
                <summary>怎么拍、表情、禁止项</summary>
                <label>怎么拍<textarea className="short" value={shot.camera || ""} onChange={(e) => editShot("camera", e.target.value)} /></label>
                <label>表情 / 光<textarea className="short" value={shot.look || ""} onChange={(e) => editShot("look", e.target.value)} /></label>
                <label>这一镜新信息<input value={shot.new_info || ""} onChange={(e) => editShot("new_info", e.target.value)} /></label>
                <label>禁止<textarea className="short" value={shot.negatives || ""} onChange={(e) => editShot("negatives", e.target.value)} /></label>
                <pre>{shot.compiled_prompt}</pre>
                {shot.compiled_h3 ? (
                  <pre>{`soundscape: ${shot.compiled_h3.overall_soundscape}\nmusic: ${shot.compiled_h3.non_diegetic_music}`}</pre>
                ) : null}
              </details>
            </>
          ) : null}
        </section>
        <aside>
          {shot?.video_url ? <video src={shot.video_url} controls style={{ width: "100%", background: "#000" }} /> : <p className="dim">这条还没有成片</p>}
          <details className="soft">
            <summary>对照剧本</summary>
            <pre>{bible || "还没有 ep01.md"}</pre>
          </details>
        </aside>
      </div>
      <details className="soft">
        <summary>审查、出图任务、收到的图</summary>
        <div className="toolbar">
          <button className="ghost" onClick={reviewDraft} disabled={busy === "review"}>
            {busy === "review" ? "审查中…" : "先审查"}
          </button>
          <button className="ghost" onClick={writeTask} disabled={busy === "task" || useDraft}>
            {busy === "task" ? "写任务单…" : "复制出图任务"}
          </button>
          <button className="ghost" onClick={scanDrop} disabled={busy === "scan"}>
            {busy === "scan" ? "扫描中…" : "扫描收到的图"}
          </button>
        </div>
        {review?.verdict ? <p className={review.verdict === "REVISE" ? "warn" : "ok"}>审查 {review.verdict}，不挡你接受正式表。</p> : null}
        {inbox?.ingested?.length ? <p className="ok">收到 {inbox.ingested.length} 张候选，还没覆盖正式首帧</p> : null}
        {inbox?.unmatched?.length ? <p className="warn">未匹配：{inbox.unmatched.join(", ")}</p> : null}
        {task?.id === shot?.id ? <pre>{JSON.stringify(task, null, 2)}</pre> : null}
        {review?.markdown ? <pre>{review.markdown}</pre> : null}
      </details>
    </div>
  );
}
