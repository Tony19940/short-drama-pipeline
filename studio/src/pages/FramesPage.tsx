import { useEffect, useState } from "react";
import { get, post } from "../api";

export function FramesPage({ slug, onChanged }: { slug: string; onChanged: () => void }) {
  const [board, setBoard] = useState<any>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [selected, setSelected] = useState(0);
  const [pipe, setPipe] = useState<any>(null);

  async function load(jumpMissing = false) {
    const next = await get(`/api/productions/${slug}/frames`);
    const pipeline = await get(`/api/productions/${slug}/pipeline`).catch(() => null);
    setPipe(pipeline);
    setBoard(next);
    if (jumpMissing) {
      const firstOpen = (next.shots || []).findIndex((shot: any) => !shot.url);
      if (firstOpen >= 0) setSelected(firstOpen);
    }
  }
  useEffect(() => {
    load(true).catch((err) => setError(err.message));
  }, [slug]);

  async function generate(shotId: string, prompt: string) {
    setBusy(shotId);
    setError("");
    try {
      await post(`/api/productions/${slug}/frames/generate`, { shotId, prompt });
      await load(false);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function lock(candidateId: string, dest: string) {
    await post(`/api/productions/${slug}/frames/lock`, { candidateId, dest });
    await load(true);
    onChanged();
  }

  async function upload(shot: any, file: File) {
    const form = new FormData();
    form.set("target", shot.id);
    form.set("dest", shot.dest);
    form.set("parent", shot.parent?.path || "");
    form.set("file", file);
    const res = await fetch(`/api/productions/${slug}/frames/upload`, { method: "POST", body: form });
    const body = await res.json();
    if (!res.ok) throw new Error(body.error);
    await lock(body.id, shot.dest);
  }

  if (!board) return <p className="dim">读取首帧…</p>;
  const shots = board.shots || [];
  const shot = shots[selected];
  if (!shot) return <p className="dim">还没有分镜</p>;
  const promptId = `prompt-${shot.id}`;
  return (
    <div>
      {pipe?.artifacts?.packages?.exists && pipe?.artifacts?.packages?.confirmed === false ? <p className="warn">生成包还没确认，不能出关键帧。</p> : null}
      {error ? <p className="err">{error}</p> : null}
      <div className="strip">
        {shots.map((item: any, index: number) => (
          <button
            key={item.id}
            className={`strip-card ${index === selected ? "on" : ""}`}
            onClick={() => setSelected(index)}
          >
            {item.url ? <img src={item.url} alt="" /> : <div className="thumb" />}
            <div>
              <b>{item.id}</b>
              <div className={item.url ? "ok" : "warn"}>{item.url ? "已锁" : "缺首帧"}</div>
            </div>
          </button>
        ))}
      </div>
      <section className="card pad">
        <div className="grid cols-2">
          <div>
            <h3>
              {shot.id} · {selected + 1}/{shots.length}
            </h3>
            <p className="dim">{shot.parent?.reason || "无父图"}</p>
            <p>第 0 秒：{shot.start || "还没写 start"}</p>
            {shot.sequence_ok === false ? <p className="warn">{shot.sequence_reason}</p> : null}
            {shot.missing_sheets?.length ? <p className="warn">缺联络板：{shot.missing_sheets.join(", ")}</p> : null}
            <p className="dim">左父图，右当前锁定。只改一件事。</p>
            <div className="grid cols-2">
              {shot.parent?.exists ? <img src={`/media/${slug}/${shot.parent.path}`} alt="" /> : <p className="bad">还没有父图</p>}
              {shot.url ? <img className="thumb" src={shot.url} alt="" /> : <div className="thumb" />}
            </div>
          </div>
          <div>
            <textarea defaultValue={shot.still_prompt || shot.video_prompt || shot.prompt} id={promptId} />
            <div className="toolbar">
              <button
                className="danger"
                disabled={busy === shot.id}
                onClick={() =>
                  generate(shot.id, (document.getElementById(promptId) as HTMLTextAreaElement).value)
                }
              >
                {busy === shot.id ? "改图中…" : "从父图改一张"}
              </button>
              <label className="ghost">
                手传
                <input
                  type="file"
                  hidden
                  accept="image/*"
                  onChange={(e) => e.target.files && upload(shot, e.target.files[0]).catch((err) => setError(err.message))}
                />
              </label>
              {selected < shots.length - 1 ? (
                <button className="ghost" onClick={() => setSelected(selected + 1)}>
                  下一镜
                </button>
              ) : null}
            </div>
            {(shot.candidates || []).map((item: any) => (
              <figure key={item.id} className="card" style={{ marginTop: 8 }}>
                <img src={item.url} alt="" />
                <figcaption>
                  <button className="pill" disabled={shot.sequence_ok === false} onClick={() => lock(item.id, shot.dest)}>
                    用这张
                  </button>
                </figcaption>
              </figure>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
