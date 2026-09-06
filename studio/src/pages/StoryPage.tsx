import { useEffect, useState } from "react";
import { get, post } from "../api";
import { AgentBar } from "../AgentBar";

export function StoryPage({
  slug,
  gate,
  onChanged,
}: {
  slug: string;
  gate?: any;
  previous?: any;
  onChanged: () => void;
  onContinue?: () => void;
}) {
  const [data, setData] = useState<any>(null);
  const [title, setTitle] = useState("");
  const [logline, setLogline] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [inkosNote, setInkosNote] = useState("");

  async function load() {
    setData(await get(`/api/productions/${slug}/story`));
  }
  useEffect(() => {
    load().catch((err) => setError(err.message));
  }, [slug]);

  async function saveBrief() {
    setBusy("brief");
    setError("");
    try {
      setData(await post(`/api/productions/${slug}/story/brief`, { title, logline, notes }));
      onChanged();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function openInkos() {
    setBusy("inkos");
    setError("");
    setInkosNote("");
    try {
      const next = await post(`/api/productions/${slug}/story/inkos`, { title, logline, notes });
      setData(next);
      setInkosNote(next?.inkos?.note || "已尝试打开 InkOS");
      onChanged();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function upload(file: File) {
    setBusy("upload");
    setError("");
    try {
      const form = new FormData();
      form.set("file", file);
      const res = await fetch(`/api/productions/${slug}/story/upload`, { method: "POST", body: form });
      const body = await res.json();
      if (!res.ok) throw new Error(body.error || res.statusText);
      setData(body);
      onChanged();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  if (!data) return <p className="dim">读取故事源…</p>;
  const view = data.migrated_view;
  const drafts = Object.entries(data.drafts || {});
  return (
    <div className="flow-main">
      <AgentBar slug={slug} station="novel" onDone={() => { load().catch(() => undefined); onChanged(); }} />
{error ? <p className="err">{error}</p> : null}
      {data.migrated || gate?.locked ? (
        <section className="card pad path-card">
          <h2>故事已接上</h2>
          <p className="ok">从现有剧本只读合成，没有改写正式文件。</p>
          <p className="dim">底部可进编剧。要新写一版，仍可启动 InkOS，导出后再上传。</p>
        </section>
      ) : null}
      {(
        <section className="card pad path-card">
          <h2>第一步：去 InkOS 写小说</h2>
          <p className="dim">先写一句话，再启动 InkOS。导演台不代写。写完导出后，再回到这里上传。</p>
          <label>
            标题
            <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="剧名" />
          </label>
          <label>
            一句话
            <textarea className="short" value={logline} onChange={(e) => setLogline(e.target.value)} placeholder="谁，因为什么，必须当场做什么" />
          </label>
          <label>
            备注
            <textarea className="short" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="时长、场次、不要出现的东西" />
          </label>
          <div className="toolbar">
            <button className="danger" disabled={!!busy} onClick={openInkos}>
              {busy === "inkos" ? "正在打开…" : "启动并跳转 InkOS"}
            </button>
            <button className="ghost" disabled={!!busy} onClick={saveBrief}>
              {busy === "brief" ? "写入中…" : "只保存简报"}
            </button>
          </div>
          {inkosNote ? <p className="ok">{inkosNote}</p> : null}
        </section>
      )}
      <section className="card pad path-card">
        <h2>写完后上传</h2>
        <p className="dim">把 InkOS 导出的小说，或已经写好的分集剧本丢进来。</p>
        <label className="file-drop">
          {busy === "upload" ? "识别中…" : "选择 md / txt / docx / pdf"}
          <input
            type="file"
            hidden
            accept=".md,.txt,.docx,.pdf"
            onChange={(e) => e.target.files && upload(e.target.files[0])}
          />
        </label>
        {data.kind ? <p className="ok">识别为：{data.kind === "script" ? "已是剧本" : "小说，锁关后去编剧改编"}</p> : null}
      </section>
      {view?.outline ? (
        <details className="soft">
          <summary>现有大纲（只读）</summary>
          <pre className="dim">{String(view.outline).slice(0, 2000)}</pre>
        </details>
      ) : null}
      {drafts.length ? (
        <details className="soft">
          <summary>未锁定的草稿 {drafts.length} 份</summary>
          {drafts.map(([name, body]) => (
            <details key={name} className="soft">
              <summary>{name}</summary>
              <pre className="dim">{String(body).slice(0, 2000)}</pre>
            </details>
          ))}
        </details>
      ) : null}
    </div>
  );
}
