import { useEffect, useState } from "react";
import { get, post, put } from "../api";
import { AgentBar } from "../AgentBar";

export function PackagePage({ slug, onChanged }: { slug: string; onChanged: () => void }) {
  const [data, setData] = useState<any>(null);
  const [selected, setSelected] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  async function load() {
    let next = await get(`/api/productions/${slug}/pipeline/gen_packages.json`);
    setData(next);
  }
  useEffect(() => {
    load().catch((err: any) => setError(err.message));
  }, [slug]);

  const packages = data?.packages || data?.gen_packages || [];
  const item = packages[selected];
  const confirmed = Boolean(data?.confirmed) && packages.every((row: any) => row.confirmed);

  function edit(key: string, value: string) {
    if (!data) return;
    const next = structuredClone(data);
    const rows = next.packages || next.gen_packages;
    rows[selected][key] = value;
    setData(next);
  }

  async function save() {
    setBusy("save");
    setError("");
    try {
      await put(`/api/productions/${slug}/pipeline/gen_packages.json`, data);
      onChanged();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function confirm() {
    setBusy("confirm");
    setError("");
    try {
      setData(await post(`/api/productions/${slug}/pipeline/confirm`, { confirmed: true }));
      onChanged();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  if (!data) return <p className="dim">读取生成包…</p>;
  return (
    <div className="flow-main">
      <AgentBar slug={slug} station="package" onDone={() => { load().catch(() => undefined); onChanged(); }} />
{error ? <p className="err">{error}</p> : null}
      <p className={confirmed ? "ok" : "warn"}>{confirmed ? "已确认，可以出关键帧。" : "未确认。关键帧和出片按钮应停住。"}</p>
      <div className="strip">
        {packages.map((row: any, index: number) => (
          <button key={row.shot_id || index} className={`strip-card ${index === selected ? "on" : ""}`} onClick={() => setSelected(index)}>
            <div>
              <b>{row.shot_id}</b>
              <div className="dim">{row.gen_mode} · {row.duration_sec}s</div>
            </div>
          </button>
        ))}
      </div>
      {item ? (
        <section className="card pad">
          <h2>{item.shot_id}</h2>
          <p className="dim">关键帧路径必须空。这里只引用已有资产。</p>
          <label>画面提示词<textarea value={item.image_prompt || ""} onChange={(e) => edit("image_prompt", e.target.value)} /></label>
          <label>运动提示词<textarea value={item.motion_prompt || ""} onChange={(e) => edit("motion_prompt", e.target.value)} /></label>
          <div className="grid cols-2">
            <label>方式<input value={item.gen_mode || ""} onChange={(e) => edit("gen_mode", e.target.value)} /></label>
            <label>模型<input value={item.target_model || ""} onChange={(e) => edit("target_model", e.target.value)} /></label>
          </div>
          <p className="dim">资产：{(item.asset_refs || []).join("、") || "无"}</p>
          <div className="toolbar">
            <button className="ghost" disabled={busy === "save"} onClick={save}>
              保存计划
            </button>
            <button className="danger" disabled={busy === "confirm"} onClick={confirm}>
              {busy === "confirm" ? "确认中…" : "确认生成本集"}
            </button>
          </div>
        </section>
      ) : (
        <p className="warn">还没有生成包。先有说明书，再种子/保存。</p>
      )}
    </div>
  );
}
