import { useEffect, useState } from "react";
import { get, post, put } from "../api";
import { AgentBar } from "../AgentBar";
import { QcPage } from "./QcPage";

export function CutPage({ slug, gate, onChanged }: { slug: string; gate?: any; onChanged: () => void }) {
  const [cut, setCut] = useState<any>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  async function load() {
    const next = await get(`/api/productions/${slug}/pipeline/cut.json`);
    setCut(next);
  }
  useEffect(() => {
    load().catch(() => setCut({ timeline: [], dropped_shot_ids: [], final_file: "06-export/ep01.mp4" }));
  }, [slug]);

  async function save() {
    setBusy("save");
    setError("");
    try {
      await put(`/api/productions/${slug}/pipeline/cut.json`, cut);
      onChanged();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function assemble() {
    setBusy("cut");
    setError("");
    try {
      if (cut) await put(`/api/productions/${slug}/pipeline/cut.json`, cut);
      await post(`/api/productions/${slug}/assemble`);
      await load();
      onChanged();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  function patch(index: number, key: string, value: string | boolean) {
    const next = structuredClone(cut);
    next.timeline[index][key] = typeof value === "boolean" ? value : Number(value);
    setCut(next);
  }

  const rows = cut?.timeline || [];
  return (
    <div className="flow-main">
      <AgentBar slug={slug} station="edit" onDone={() => { load().catch(() => undefined); onChanged(); }} />
{error ? <p className="err">{error}</p> : null}
      <section className="card pad path-card">
        <h2>按时间线剪</h2>
        <p className="dim">默认切到说明书秒数。模型出 5 秒也不能整段上屏。可以删镜。</p>
        <table className="plain">
          <thead>
            <tr>
              <th>用</th>
              <th>镜</th>
              <th>入点</th>
              <th>出点</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row: any, index: number) => (
              <tr key={row.shot_id || index}>
                <td>
                  <input type="checkbox" checked={row.used !== false} onChange={(e) => patch(index, "used", e.target.checked)} />
                </td>
                <td>{row.shot_id}</td>
                <td>
                  <input value={row.in_point ?? 0} onChange={(e) => patch(index, "in_point", e.target.value)} />
                </td>
                <td>
                  <input value={row.out_point ?? 0} onChange={(e) => patch(index, "out_point", e.target.value)} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="toolbar">
          <button className="ghost" disabled={!!busy} onClick={save}>
            保存时间线
          </button>
          <button className="danger" disabled={!!busy} onClick={assemble}>
            {busy === "cut" ? "剪辑中…" : "按时间线出成片"}
          </button>
        </div>
      </section>
      <QcPage slug={slug} gate={gate} onChanged={onChanged} />
    </div>
  );
}
