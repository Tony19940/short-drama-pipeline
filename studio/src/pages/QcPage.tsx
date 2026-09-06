import { useEffect, useState } from "react";
import { get, post } from "../api";

export function QcPage({
  slug,
  onChanged,
}: {
  slug: string;
  gate?: any;
  previous?: any;
  onChanged: () => void;
}) {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    setData(await get(`/api/productions/${slug}/qc`));
  }
  useEffect(() => {
    load().catch((err) => setError(err.message));
  }, [slug]);

  async function draft() {
    setBusy(true);
    setError("");
    try {
      setData(await post(`/api/productions/${slug}/qc/draft`));
      onChanged();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (!data) return <p className="dim">读取审片…</p>;
  const report = data.official || data.draft || data.live || {};
  return (
    <div className="flow-main">
      {error ? <p className="err">{error}</p> : null}
      <section className="card pad path-card">
        <h2>看成片</h2>
        {data.export_exists ? <p className="ok">06-export/ep01.mp4</p> : <p className="warn">还没有成片，先回摄影派出。</p>}
        <video src={`/media/${slug}/06-export/ep01.mp4`} controls style={{ width: "min(360px, 100%)", background: "#000" }} />
        <p>
          脚本 {report.required || "—"} · 画面 {report.visual || "要人看"} · 结论 {report.verdict || "—"}
        </p>
        <button className="danger" disabled={busy} onClick={draft}>
          {busy ? "出报告中…" : "出审片报告"}
        </button>
      </section>
      {(report.rework || []).length ? (
        <section className="card pad">
          <h3>返工</h3>
          <ul>
            {report.rework.map((item: any) => (
              <li key={item.id} className="warn">
                {item.id}：{(item.reasons || []).join("；")}
              </li>
            ))}
          </ul>
        </section>
      ) : (
        <p className="dim">没有脚本返工项。画面对错仍要人看完再锁定。</p>
      )}
    </div>
  );
}
