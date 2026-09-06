import { useEffect, useRef, useState } from "react";
import { get, post } from "../api";

function hasVideo(shot: any) {
  return Boolean(shot.video_exists || shot.video_url);
}

function modeLabel(item: any) {
  if (item.mode === "flf") return "首尾帧：设计首帧 + 设计尾帧";
  if (item.source_kind === "last_frame") return "同场续：上一镜真末帧再 FL2VA";
  if (item.mode === "r2v") return "首帧图生 + 参考锁脸";
  return "首帧图生（FL2VA）";
}

export function RenderPage({ slug, onChanged }: { slug: string; onChanged: () => void }) {

  const [board, setBoard] = useState<any>(null);
  const [jobs, setJobs] = useState<any[]>([]);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [preview, setPreview] = useState<any>(null);
  const [pipe, setPipe] = useState<any>(null);
  const [busy, setBusy] = useState("");
  const picked = useRef(false);

  async function load() {
    const shots = await get(`/api/productions/${slug}/shots`);
    const pipeline = await get(`/api/productions/${slug}/pipeline`).catch(() => null);
    setPipe(pipeline);
    const jobData = await get(`/api/productions/${slug}/jobs`);
    setBoard(shots);
    setJobs(jobData.jobs || []);
    if (!picked.current) {
      picked.current = true;
      setSelected((shots.shots || []).filter((shot: any) => !hasVideo(shot)).map((shot: any) => shot.id));
    }
  }
  useEffect(() => {
    picked.current = false;
    load().catch((err) => setError(err.message));
    const timer = setInterval(() => load().catch(() => undefined), 4000);
    return () => clearInterval(timer);
  }, [slug]);

  function toggle(id: string) {
    setSelected((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]));
    setPreview(null);
  }

  async function prepare() {
    setError("");
    setBusy("prepare");
    try {
      const data = await post(`/api/productions/${slug}/render/prepare`, {
        shotIds: selected.length ? selected : undefined,
      });
      setPreview(data);
    } catch (err: any) {
      setError(err.message);
      setPreview(null);
    } finally {
      setBusy("");
    }
  }

  async function render() {
    if (!preview?.fingerprint) {
      setError("先预览这批镜头，确认后再派出");
      return;
    }
    setError("");
    setBusy("render");
    try {
      await post(`/api/productions/${slug}/render`, {
        shotIds: selected.length ? selected : undefined,
        fingerprint: preview.fingerprint,
      });
      setPreview(null);
      await load();
      onChanged();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  if (!board) return <p className="dim">读取出片状态…</p>;
  const missing = (board.shots || []).filter((shot: any) => !hasVideo(shot)).length;
  return (
    <div className="flow-main">
      <section className="card pad path-card">
        <h2>派出成片</h2>
        <p className="dim">未勾选时派出缺视频的镜头。先预览，确认后再派出。</p>
        <p>{missing ? `${missing} 镜还没有视频` : "8 镜都有视频，重派请勾选"}</p>
        <div className="toolbar">
          <button className="ghost" disabled={busy === "prepare"} onClick={prepare}>
            {busy === "prepare" ? "预览中…" : "先预览这批"}
          </button>
          <button className="danger" disabled={!preview?.fingerprint || busy === "render"} onClick={render}>
            {busy === "render" ? "派出中…" : "确认并派出"}
          </button>
        </div>
        {pipe?.artifacts?.packages?.exists && pipe?.artifacts?.packages?.confirmed === false ? <p className="warn">生成包还没确认，不能派出。</p> : null}
        {error ? <p className="err">{error}</p> : null}
      </section>
      {preview ? (
        <section className="card pad">
          <b>{preview.count} 镜待出</b>
          <div className="dim">{preview.note}</div>
          {(preview.shots || []).map((item: any) => (
            <div key={item.id} className="dim" style={{ marginTop: 8 }}>
              <b>{item.id}</b> · {modeLabel(item)} · 从 {item.source || item.parent || "无"} 起
              <details className="soft">
                <summary>给模型的句子</summary>
                <div>参考 {(item.refs || []).join(", ") || "无"}{item.end_frame ? ` · 设计尾帧 ${item.end_frame}` : ""}</div>
                <pre>{item.compiled}</pre>
              </details>
            </div>
          ))}
        </section>
      ) : null}
      {(board.shots || []).map((shot: any) => (
        <label key={shot.id} className="card pad render-row" style={{ marginBottom: 8 }}>
          <input type="checkbox" checked={selected.includes(shot.id)} onChange={() => toggle(shot.id)} />
          <b>{shot.id}</b>
          <span className={hasVideo(shot) ? "ok" : shot.frame_url ? "warn" : "bad"}>
            {hasVideo(shot) ? "已有成片" : shot.frame_url ? "待派出" : "缺首帧"}
          </span>
          <span className="dim">{shot.i2v?.reason || ""}</span>
        </label>
      ))}
      <details className="soft">
        <summary>派出记录 {jobs.length ? `(${jobs.length})` : ""}</summary>
        {jobs.map((job) => (
          <div key={job.id} className="card pad" style={{ marginBottom: 8 }}>
            <b>{job.id}</b> · {({render:"出片", review:"审片"} as Record<string,string>)[job.kind] || job.kind} · <span className={job.status === "ready" ? "ok" : job.status === "failed" ? "bad" : "warn"}>{({queued:"排队中", running:"生成中", ready:"已完成", failed:"失败"} as Record<string,string>)[job.status] || job.status}</span>
            <div className="dim">{(job.shot_ids || []).join(" ")}</div>
            {job.error ? <div className="err">{job.error}</div> : null}
            <div className="dim">{(job.log || [])[0]}</div>
          </div>
        ))}
      </details>
    </div>
  );
}
