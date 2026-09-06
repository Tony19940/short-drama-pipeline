import { useEffect, useState } from "react";
import { get, post, put } from "../api";
import { AgentBar } from "../AgentBar";
import { ProducerPage } from "./ProducerPage";

const CHAR_SLOTS = ["master", "face", "front", "side", "back", "sheet"];
const SCENE_SLOTS = ["master", "door", "table", "sheet"];
const SLOT_LABELS: Record<string, string> = {
  master: "主图",
  face: "脸锁",
  front: "正面",
  side: "侧面",
  back: "背面",
  sheet: "联络板",
  door: "门",
  table: "桌",
};

export function AssetsPage({ slug, onChanged }: { slug: string; onChanged: () => void }) {
  const [data, setData] = useState<any>(null);
  const [look, setLook] = useState("");
  const [error, setError] = useState("");
  const [copied, setCopied] = useState("");
  const [tasks, setTasks] = useState<any[]>([]);
  const [kind, setKind] = useState<"characters" | "scenes" | "props">("characters");
  const [selected, setSelected] = useState(0);

  async function load() {
    const [next, producer] = await Promise.all([
      get(`/api/productions/${slug}/assets`),
      get(`/api/productions/${slug}/producer`).catch(() => null),
    ]);
    setData(next);
    setTasks(producer?.manifest?.tasks || producer?.live?.tasks || []);
    setLook((cur) => (document.activeElement?.tagName === "TEXTAREA" ? cur : next.look || ""));
    onChanged();
  }

  useEffect(() => {
    load().catch((err) => setError(err.message));
    const timer = setInterval(() => load().catch(() => undefined), 4000);
    return () => clearInterval(timer);
  }, [slug]);

  useEffect(() => {
    setSelected(-1);
  }, [kind, slug]);

  useEffect(() => {
    if (!data || selected !== -1) return;
    const items = kind === "characters" ? data.characters : kind === "scenes" ? data.scenes : data.props || [];
    const wanted = tasks.find((task: any) =>
      (kind === "characters" && task.kind === "character") ||
      (kind === "scenes" && task.kind === "scene") ||
      (kind === "props" && task.kind === "prop"),
    )?.slug;
    const idx = items.findIndex((entry: any) => entry.id === wanted || (kind === "characters" && !entry.sheet));
    setSelected(idx >= 0 ? idx : 0);
  }, [data, kind, selected, tasks]);

  async function saveLook() {
    await put(`/api/productions/${slug}/assets/look`, { content: look });
    await load();
  }

  async function copyPath(rel: string) {
    await navigator.clipboard.writeText(rel);
    setCopied(rel);
  }

  if (!data) return <p className="dim">读取资产…</p>;
  const items = kind === "characters" ? data.characters : kind === "scenes" ? data.scenes : data.props || [];
  const item = selected >= 0 ? items[selected] : undefined;
  const slots = kind === "characters" ? CHAR_SLOTS : kind === "scenes" ? SCENE_SLOTS : ["master"];
  return (
    <div className="flow-main">
      <AgentBar slug={slug} station="assets" onDone={() => { load().catch(() => undefined); onChanged(); }} />
{error ? <p className="err">{error}</p> : null}
      <details className="soft" open>
        <summary>缺口清单（不在这里生图）</summary>
        <ProducerPage slug={slug} onChanged={onChanged} />
      </details>
      <section className="card pad path-card">
        <h2>按任务单补图</h2>
        <p className="dim">出图在 Codex 里下令，写进 02-assets。主图只许全新一次，正侧背和联络板都从主图改，不要另开新脸。</p>
        {tasks.length ? (
          <ul>
            {tasks.map((task: any) => (
              <li key={`${task.kind}-${task.slug}`}>
                {task.kind} {task.slug} 缺 {(task.missing || []).join("、")}
              </li>
            ))}
          </ul>
        ) : (
          <p className="ok">制片任务单无缺口，对一下脸和空镜就能锁定。</p>
        )}
        {copied ? <p className="ok">已复制 {copied}</p> : null}
      </section>
      <div className="subpath">
        <button className={kind === "characters" ? "on" : ""} onClick={() => setKind("characters")}>
          人物
        </button>
        <button className={kind === "scenes" ? "on" : ""} onClick={() => setKind("scenes")}>
          场景
        </button>
        <button className={kind === "props" ? "on" : ""} onClick={() => setKind("props")}>
          道具
        </button>
      </div>
      <div className="strip">
        {items.map((entry: any, index: number) => (
          <button key={entry.id} className={`strip-card ${index === selected ? "on" : ""}`} onClick={() => setSelected(index)}>
            {entry.master_url || entry.face_url ? <img src={entry.master_url || entry.face_url} alt="" /> : <div className="thumb" />}
            <div>
              <b>{entry.id}</b>
              {kind === "characters" ? <div className={entry.sheet ? "ok" : "warn"}>{entry.sheet ? "联络板齐" : "缺联络板"}</div> : null}
            </div>
          </button>
        ))}
      </div>
      {item ? (
        <section className="card pad">
          <h3>{item.id}</h3>
          {kind === "characters" ? (
            <p className={item.sheet ? "ok" : "warn"}>{item.sheet ? "联络板已齐" : "还缺联络板，新首帧不能锁"}</p>
          ) : null}
          <div className="media-grid">
            {kind === "props" ? (
              <>
                <figure>
                  {item.master_url ? <img className="thumb" src={item.master_url} alt="" /> : <div className="thumb" />}
                  <figcaption>
                    <b>主图</b>
                    <button className="pill" onClick={() => copyPath(item.path || `02-assets/props/${item.id}/master.jpg`)}>
                      复制路径
                    </button>
                  </figcaption>
                </figure>
                {(item.files || []).map((file: any) => (
                  <figure key={file.id}>
                    {file.url ? <img className="thumb" src={file.url} alt="" /> : <div className="thumb" />}
                    <figcaption>{file.id}</figcaption>
                  </figure>
                ))}
              </>
            ) : (
              slots.map((slot) => (
                <figure key={slot}>
                  {item[`${slot}_url`] ? <img className="thumb" src={item[`${slot}_url`]} alt="" /> : <div className="thumb" />}
                  <figcaption>
                    <b>{SLOT_LABELS[slot] || slot}</b>
                    <button className="pill" onClick={() => copyPath(`02-assets/${kind}/${item.id}/${slot}.jpg`)}>
                      复制路径
                    </button>
                  </figcaption>
                </figure>
              ))
            )}
          </div>
        </section>
      ) : (
        <p className="dim">这一类还没有图。</p>
      )}
      {data.scale_url ? (
        <details className="soft">
          <summary>身高锁</summary>
          <img src={data.scale_url} alt="" style={{ maxWidth: 220 }} />
        </details>
      ) : null}
      <details className="soft">
        <summary>画风 LOOK.md</summary>
        <textarea value={look} onChange={(e) => setLook(e.target.value)} />
        <div className="toolbar">
          <button className="ghost" onClick={saveLook}>
            保存画风
          </button>
        </div>
      </details>
    </div>
  );
}
