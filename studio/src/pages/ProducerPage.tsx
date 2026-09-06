import { useEffect, useState } from "react";
import { get, post } from "../api";

export function ProducerPage({
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
    setData(await get(`/api/productions/${slug}/producer`));
  }
  useEffect(() => {
    load().catch((err) => setError(err.message));
  }, [slug]);

  async function draft() {
    setBusy(true);
    setError("");
    try {
      setData(await post(`/api/productions/${slug}/producer/draft`));
      onChanged();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (!data) return <p className="dim">读取制片任务单…</p>;
  const manifest = data.manifest || data.live || {};
  const tasks = manifest.tasks || [];
  return (
    <div className="flow-main">
      {error ? <p className="err">{error}</p> : null}
      <section className="card pad path-card">
        <h2>缺什么就列什么</h2>
        <p className="dim">不在这里生图。扫完把路径交给美术。</p>
        <p>
          {manifest.shot_count || 0} 镜 · 缺口 <b>{manifest.task_count || 0}</b> 项
        </p>
        <button className="danger" disabled={busy} onClick={draft}>
          {busy ? "扫描中…" : tasks.length || data.drafts ? "再扫一遍" : "扫描缺口"}
        </button>
      </section>
      <table className="plain">
        <thead>
          <tr>
            <th>缺什么</th>
            <th>谁</th>
            <th>路径</th>
          </tr>
        </thead>
        <tbody>
          {tasks.length ? (
            tasks.map((task: any) => (
              <tr key={`${task.kind}-${task.slug}`}>
                <td>{(task.missing || []).join("、")}</td>
                <td>
                  {task.kind} {task.slug}
                </td>
                <td className="dim">{task.dest}</td>
              </tr>
            ))
          ) : (
            <tr>
              <td colSpan={3} className="ok">
                没有缺口，可以锁定去美术确认
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
