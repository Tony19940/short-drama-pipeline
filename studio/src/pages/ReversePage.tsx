import { useEffect, useState } from "react";
import { get, post } from "../api";

const DEFAULT_BRIEF =
  "把故事改成金边都市短剧。人名用高棉名；地点用制衣厂、出租房、borey、钻石岛或路边婚礼棚；服装用厂服、sampot、sbai。禁止旗袍、故宫、微信、人民币机关。";

export function ReversePage({ slug, onChanged }: { slug: string; onChanged: () => void }) {
  const [data, setData] = useState<any>(null);
  const [brief, setBrief] = useState(DEFAULT_BRIEF);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [selected, setSelected] = useState(0);

  async function load() {
    const next = await get(`/api/productions/${slug}/reverse`);
    setData(next);
  }

  useEffect(() => {
    load().catch((err) => setError(err.message));
  }, [slug]);

  async function upload(file: File) {
    setBusy("upload");
    setError("");
    try {
      const body = new FormData();
      body.append("file", file);
      const res = await fetch(`/api/productions/${slug}/reverse/upload`, { method: "POST", body });
      const json = await res.json();
      if (!res.ok) throw new Error(json.error || res.statusText);
      await load();
      onChanged();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function analyze() {
    setBusy("analyze");
    setError("");
    try {
      await post(`/api/productions/${slug}/reverse/analyze`, { brief, useGrok: true });
      await load();
      onChanged();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function localize() {
    setBusy("localize");
    setError("");
    try {
      await post(`/api/productions/${slug}/reverse/localize`, { brief, useGrok: true });
      await load();
      onChanged();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  const shots = data?.draft?.shots || [];
  const shot = shots[selected];

  return (
    <div className="desk">
      <aside className="desk-script">
        <h2>参考片</h2>
        <label className="ghost" style={{ display: "inline-flex", alignItems: "center", height: 36 }}>
          {busy === "upload" ? "上传中…" : "选择视频"}
          <input
            type="file"
            accept="video/mp4,video/quicktime,video/webm,.mp4,.mov,.webm,.m4v"
            hidden
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) upload(file);
              e.currentTarget.value = "";
            }}
          />
        </label>
        {data?.video_url ? <video src={data.video_url} controls style={{ marginTop: 12, width: "100%" }} /> : <p className="dim">还没有参考视频</p>}
        {data?.source?.duration ? (
          <p className="dim">
            {data.source.duration}s · {data.source.width}x{data.source.height} · {data.source.aspect}
          </p>
        ) : null}
        <label>
          柬埔寨改写说明
          <textarea className="short" value={brief} onChange={(e) => setBrief(e.target.value)} />
        </label>
        <div className="toolbar">
          <button className="danger" onClick={analyze} disabled={!data?.has_source || !!busy}>
            {busy === "analyze" ? "分析中…" : "分析成草稿"}
          </button>
          <button className="ghost" onClick={localize} disabled={!shots.length || !!busy}>
            {busy === "localize" ? "改写中…" : "改成柬埔寨"}
          </button>
        </div>
        {data?.analysis?.origin ? <p className="ok">分析来源：{data.analysis.origin}</p> : null}
        {data?.draft?.origin ? <p className="dim">当前草稿来自：{data.draft.origin}</p> : null}
        {data?.analysis?.grok_error ? <p className="warn">Grok 没写上，先用切镜草稿。{data.analysis.grok_error}</p> : null}
        {error ? <p className="err">{error}</p> : null}
        <p className="dim">{data?.whisper_model ? "对白已转写" : "先切镜，对白可后补"}</p>
      </aside>
      <section className="desk-strip">
        <h2>反推镜头</h2>
        {!shots.length ? <p className="dim">分析完成后会出现镜头条</p> : null}
        <div className="strip">
          {shots.map((item: any, index: number) => (
            <button
              key={item.id}
              className={`strip-card ${index === selected ? "on" : ""}`}
              onClick={() => setSelected(index)}
            >
              {item.source_frame ? (
                <img src={`/media/${slug}/${item.source_frame}`} alt="" />
              ) : (
                <div className="thumb" />
              )}
              <div>
                <b>{item.id}</b> {item.seconds}s
                <div className="dim">
                  {item.setup} / {item.move}
                </div>
                <div className="dim">
                  {item.source_start ?? "?"}–{item.source_end ?? "?"}
                </div>
              </div>
            </button>
          ))}
        </div>
      </section>
      <aside className="desk-spec">
        {shot ? (
          <>
            <h2>{shot.id} 反推说明书</h2>
            <p className="dim">{shot.new_info}</p>
            <p>
              {shot.scene} · {shot.axis} · {shot.lens}
            </p>
            <p>{(shot.characters || []).join(", ")}</p>
            <p>line：{shot.line}</p>
            <p className="dim">camera：{shot.camera}</p>
            <pre>{shot.video_prompt}</pre>
            <p className="dim">到分镜页改完，再点接受。</p>
          </>
        ) : (
          <p className="dim">还没有可审的反推镜头</p>
        )}
      </aside>
    </div>
  );
}
