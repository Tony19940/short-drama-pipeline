import { useEffect, useState } from "react";
import { get, post, put } from "../api";

export function StagePage({ slug, onChanged }: { slug: string; onChanged: () => void }) {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState(0);

  async function load() {
    setData(await get(`/api/productions/${slug}/stage`));
  }
  useEffect(() => {
    load().catch((err) => setError(err.message));
  }, [slug]);

  function updateMark(index: number, field: string, value: number | string) {
    const next = structuredClone(data);
    next.sets[selected].marks[index][field] = value;
    setData(next);
  }

  async function save() {
    setError("");
    await put(`/api/productions/${slug}/stage`, { sets: data.sets.map(({ master_url, blocking_url, master_exists, blocking_exists, ...rest }: any) => rest) });
    await load();
    onChanged();
  }

  async function renderStage() {
    setError("");
    try {
      await post(`/api/productions/${slug}/stage/render`, {});
      await load();
      onChanged();
    } catch (err: any) {
      setError(err.message);
    }
  }

  if (!data) return <p className="dim">读取舞台…</p>;
  const set = data.sets[selected];
  return (
    <div className="grid cols-2">
      <section>
        <div className="toolbar">
          {data.sets.map((item: any, index: number) => (
            <button key={item.id} className={`pill ${index === selected ? "on" : ""}`} onClick={() => setSelected(index)}>
              {item.id}
            </button>
          ))}
          <button className="ghost" onClick={save}>保存站位</button>
          <button className="danger" onClick={renderStage}>重打舞台图</button>
        </div>
        {error ? <p className="err">{error}</p> : null}
        <div className="stage-canvas">
          {set?.master_url ? <img src={set.master_url} alt="" /> : <div className="thumb" />}
          {(set?.marks || []).map((mark: any) => (
            <span key={mark.id} className="mark" style={{ left: `${mark.x * 100}%`, top: `${mark.y * 100}%` }} title={mark.note} />
          ))}
        </div>
        <p className="dim">{set?.axis}</p>
      </section>
      <section className="card pad">
        <h2>站位</h2>
        {(set?.marks || []).map((mark: any, index: number) => (
          <div key={mark.id} className="grid cols-3" style={{ marginBottom: 8 }}>
            <input value={mark.id} onChange={(e) => updateMark(index, "id", e.target.value)} />
            <input type="number" step="0.01" value={mark.x} onChange={(e) => updateMark(index, "x", Number(e.target.value))} />
            <input type="number" step="0.01" value={mark.y} onChange={(e) => updateMark(index, "y", Number(e.target.value))} />
            <input style={{ gridColumn: "1 / -1" }} value={mark.note || ""} onChange={(e) => updateMark(index, "note", e.target.value)} />
          </div>
        ))}
        {set?.blocking_url ? <img src={set.blocking_url} alt="" /> : <p className="warn">还没有舞台图</p>}
      </section>
    </div>
  );
}
