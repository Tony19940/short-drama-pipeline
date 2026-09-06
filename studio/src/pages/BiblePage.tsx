import { useEffect, useState } from "react";
import { get, post, put } from "../api";
import { AgentBar } from "../AgentBar";

export function BiblePage({ slug, onChanged }: { slug: string; onChanged: () => void }) {
  const [files, setFiles] = useState<Record<string, string>>({});
  const [current, setCurrent] = useState("01-bible/ep01.md");
  const [content, setContent] = useState("");
  const [script, setScript] = useState("");
  const [error, setError] = useState("");
  const [writer, setWriter] = useState<any>(null);
  const [checks, setChecks] = useState<string[]>([]);
  const [busy, setBusy] = useState("");
  const [preview, setPreview] = useState("");

  async function load() {
    const [data, status, issues] = await Promise.all([
      get(`/api/productions/${slug}/bible`),
      get(`/api/productions/${slug}/scriptwriter`).catch(() => null),
      get(`/api/productions/${slug}/writer-checks`).catch(() => ({ issues: [] })),
    ]);
    setFiles(data.files || {});
    setContent(data.files?.[current] || "");
    setWriter(status);
    setChecks(issues.issues || []);
  }

  useEffect(() => {
    load().catch((err) => setError(err.message));
  }, [slug]);

  useEffect(() => {
    setContent(files[current] || "");
  }, [current, files]);

  async function save() {
    setError("");
    await put(`/api/productions/${slug}/bible`, { path: current, content });
    await load();
    onChanged();
  }

  async function importScript() {
    setError("");
    if (!script.trim()) return;
    await post(`/api/productions/${slug}/script`, { text: script });
    await load();
    onChanged();
  }

  async function writeShots() {
    setBusy("write");
    setError("");
    try {
      const result = await post(`/api/productions/${slug}/scriptwriter`, { useGrok: true });
      setWriter({ status: result, overview: result.overview, shot_draft_count: result.shot_count });
      await load();
      onChanged();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  const episodeFiles = Object.keys(files).filter((path) => /ep\d+\.md$/.test(path));
  const otherFiles = Object.keys(files).filter((path) => !/ep\d+\.md$/.test(path));
  const draftFiles = [
    ["blueprint.draft.md", writer?.blueprint_draft],
    ["beats.draft.md", writer?.beats_draft],
    ["voiceover.draft.md", writer?.voiceover_draft],
  ].filter((item) => item[1]);

  return (
    <div className="flow-main">
      <AgentBar slug={slug} station="writer" onDone={() => { load().catch(() => undefined); onChanged(); }} />
{error ? <p className="err">{error}</p> : null}
      {checks.length ? (
        <div className="flow-alert">
          {checks.slice(0, 4).map((item) => (
            <p key={item}>{item}</p>
          ))}
        </div>
      ) : null}
      <section className="card pad path-card">
        <h2>改这一集</h2>
        <div className="toolbar">
          {episodeFiles.map((path) => (
            <button key={path} className={`pill ${current === path ? "on" : ""}`} onClick={() => setCurrent(path)}>
              {path.replace("01-bible/", "")}
            </button>
          ))}
        </div>
        <textarea value={content} onChange={(e) => setContent(e.target.value)} />
        <div className="toolbar">
          <button className="danger" onClick={save}>
            保存剧本
          </button>
        </div>
      </section>
      {otherFiles.length ? (
        <details className="soft">
          <summary>系列设定和其他文件</summary>
          <div className="toolbar">
            {otherFiles.map((path) => (
              <button key={path} className={`pill ${current === path ? "on" : ""}`} onClick={() => setCurrent(path)}>
                {path.replace("01-bible/", "")}
              </button>
            ))}
          </div>
        </details>
      ) : null}
      <details className="soft">
        <summary>还没有分集？贴整本拆进各集。选镜头去「分镜」岗。</summary>
        <label>
          贴整本
          <textarea value={script} onChange={(e) => setScript(e.target.value)} placeholder="按第N集拆进 epNN.md，不会自动出镜头" />
        </label>
        <div className="toolbar">
          <button className="ghost" onClick={importScript}>
            拆进各集
          </button>
          <button className="ghost" onClick={writeShots} disabled={!!busy}>
            {busy ? "写草稿中…" : "（旧）写镜头草稿，正式选镜请去分镜岗"}
          </button>
        </div>
        {writer?.overview?.title ? (
          <p className="ok">
            {writer.overview.title} · {writer.shot_draft_count || writer.status?.shot_count || 0} 镜草稿
            {writer.overview?.beat_source ? ` · 节拍来自 ${writer.overview.beat_source}` : ""}
          </p>
        ) : null}
        {writer?.status?.origin ? <p className="dim">来源：{writer.status.origin}</p> : null}
        {writer?.status?.lint?.length ? <p className="warn">自检：{writer.status.lint.join("；")}</p> : null}
        {writer?.status?.grok_error ? <p className="warn">Grok 没写上，已用现有覆盖/节拍。{writer.status.grok_error}</p> : null}
        {draftFiles.length ? (
          <div className="toolbar">
            {draftFiles.map(([name]) => (
              <button key={String(name)} className={`pill ${preview === name ? "on" : ""}`} onClick={() => setPreview(String(name))}>
                {String(name)}
              </button>
            ))}
          </div>
        ) : null}
        {preview ? <pre className="dim">{String(draftFiles.find((item) => item[0] === preview)?.[1] || "").slice(0, 4000)}</pre> : null}
      </details>
    </div>
  );
}
