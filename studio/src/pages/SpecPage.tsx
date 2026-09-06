import { useEffect, useState } from "react";
import { get, post, put } from "../api";
import { AgentBar } from "../AgentBar";

export function SpecPage({ slug, onChanged }: { slug: string; onChanged: () => void }) {
  const [data, setData] = useState<any>(null);
  const [selected, setSelected] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  async function load() {
    let next = await get(`/api/productions/${slug}/pipeline/shot_specs.json`);
    setData(next);
  }
  useEffect(() => {
    load().catch((err: any) => setError(err.message));
  }, [slug]);

  const specs = data?.shot_specs || [];
  const spec = specs[selected];

  function edit(key: string, value: string) {
    if (!data) return;
    const next = structuredClone(data);
    next.shot_specs[selected][key] = key === "duration_sec" || key === "intensity" ? Number(value) : value;
    setData(next);
  }

  async function save() {
    setBusy("save");
    setError("");
    try {
      await put(`/api/productions/${slug}/pipeline/shot_specs.json`, data);
      onChanged();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  if (!data) return <p className="dim">读取说明书…</p>;
  return (
    <div className="flow-main">
      <AgentBar slug={slug} station="spec" onDone={() => { load().catch(() => undefined); onChanged(); }} />
{error ? <p className="err">{error}</p> : null}
      <p className="dim">只写这一镜干什么、摄影机在哪、怎么接。不写模型提示词，不填资产文件名。</p>
      <div className="strip">
        {specs.map((item: any, index: number) => (
          <button key={item.shot_id || index} className={`strip-card ${index === selected ? "on" : ""}`} onClick={() => setSelected(index)}>
            <div>
              <b>{item.shot_id}</b>
              <div className="dim">{item.duration_sec}s · {item.move_type} · {item.shot_size}</div>
            </div>
          </button>
        ))}
      </div>
      {spec ? (
        <section className="card pad">
          <h2>{spec.shot_id}</h2>
          <label>拍谁<input value={spec.subject || ""} onChange={(e) => edit("subject", e.target.value)} /></label>
          <label>正在做什么<textarea className="short" value={spec.action_now || ""} onChange={(e) => edit("action_now", e.target.value)} /></label>
          <label>台词（必须是编剧原句）<input value={spec.dialogue_line || ""} onChange={(e) => edit("dialogue_line", e.target.value)} /></label>
          <div className="grid cols-2">
            <label>景别<input value={spec.shot_size || ""} onChange={(e) => edit("shot_size", e.target.value)} /></label>
            <label>焦段<input value={spec.focal_length || ""} onChange={(e) => edit("focal_length", e.target.value)} /></label>
            <label>运镜<input value={spec.move_type || ""} onChange={(e) => edit("move_type", e.target.value)} /></label>
            <label>时长秒<input value={spec.duration_sec || ""} onChange={(e) => edit("duration_sec", e.target.value)} /></label>
            <label>左<input value={spec.left || ""} onChange={(e) => edit("left", e.target.value)} /></label>
            <label>右<input value={spec.right || ""} onChange={(e) => edit("right", e.target.value)} /></label>
          </div>
          <label>为什么要动<textarea className="short" value={spec.move_reason || ""} onChange={(e) => edit("move_reason", e.target.value)} /></label>
          <div className="toolbar">
            <button className="ghost" disabled={!!busy} onClick={async () => { setBusy("seed"); try { await post(`/api/productions/${slug}/pipeline/seed`, {force:true}); await load(); onChanged(); } catch (err: any) { setError(err.message);} finally { setBusy(""); } }}>写入交接</button>
            <button className="danger" disabled={busy === "save"} onClick={save}>
              {busy === "save" ? "保存中…" : "保存说明书"}
            </button>
          </div>
        </section>
      ) : (
        <p className="warn">还没有说明书。先锁定分镜，再点保存会从旧表编译一版草稿。</p>
      )}
    </div>
  );
}
