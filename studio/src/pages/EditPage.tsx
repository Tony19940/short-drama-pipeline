import { useEffect, useState } from "react";
import { get, post } from "../api";
import { AgentBar } from "../AgentBar";
import { ReviewPage } from "./ReviewPage";

export function EditPage({
  slug,
  onChanged,
}: {
  slug: string;
  gate?: any;
  previous?: any;
  onChanged: () => void;
}) {
  const [sound, setSound] = useState<any>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    get(`/api/productions/${slug}/sound`).then(setSound).catch(() => undefined);
  }, [slug]);

  async function load() {
    setSound(await get(`/api/productions/${slug}/sound`));
  }

  async function draft() {
    setSound(await post(`/api/productions/${slug}/sound/draft`));
    onChanged();
  }

  async function mixSfx(force: boolean) {
    setError("");
    setBusy(force ? "remix" : "mix");
    try {
      const data = await post(`/api/productions/${slug}/sound/sfx`, { force, preview: true });
      setSound(await get(`/api/productions/${slug}/sound`));
      if (data?.error) setError(data.error);
      onChanged();
    } catch (err: any) {
      setError(err.message || String(err));
    } finally {
      setBusy("");
    }
  }

  const contract = sound?.official || sound?.draft || sound?.live;
  const sfx = sound?.sfx;
  const missing = sfx?.missing_clips || [];
  const canMix = sfx && sfx.shot_count > 0 && missing.length === 0;
  return (
    <div className="flow-main">
      <section className="card pad path-card">
        <h2>音效床</h2>
        <p className="dim">
          按锁定分镜表 <code>key_sfx</code> 混一条整集音效。不对白、不 BGM。Seedance 自带声不当成品。
        </p>
        {sfx ? (
          <p>
            {sfx.exists ? "已有音效床" : "还没有音效床"}
            {sfx.duration_sec ? ` · ${Number(sfx.duration_sec).toFixed(1)}s` : ""}
            {sfx.event_count ? ` · ${sfx.event_count} 条事件` : ""}
            {sfx.has_overrides ? " · 用已审 overrides" : ""}
            {" · "}
            单镜 {sfx.clip_count}/{sfx.shot_count}
          </p>
        ) : (
          <p className="dim">读取音效状态…</p>
        )}
        {missing.length ? <p className="err">缺视频 {missing.join("、")}</p> : null}
        {error ? <p className="err">{error}</p> : null}
        <div className="toolbar">
          <button className="danger" disabled={!!busy || !canMix} onClick={() => mixSfx(Boolean(sfx?.exists))}>
            {busy ? "混合中…" : sfx?.exists ? "重混音效" : "按分镜表混音效"}
          </button>
        </div>
        {sfx?.preview_url ? (
          <video key={sfx.preview_url} src={sfx.preview_url} controls style={{ width: "min(360px, 100%)", background: "#000" }} />
        ) : sfx?.url ? (
          <audio key={sfx.url} src={sfx.url} controls />
        ) : null}
        {sfx?.key_sfx?.length ? (
          <details className="soft">
            <summary>本集 key_sfx</summary>
            <table className="plain">
              <thead>
                <tr>
                  <th>镜</th>
                  <th>音效</th>
                </tr>
              </thead>
              <tbody>
                {sfx.key_sfx.map((row: any) => (
                  <tr key={row.shot_id}>
                    <td>{row.shot_id}</td>
                    <td>{(row.key_sfx || []).join("、")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        ) : null}
      </section>
      <ReviewPage slug={slug} onChanged={onChanged} />
      <details className="soft">
        <summary>声音合同（对白 / 心声 / 旁白，不进画面句）</summary>
        <button className="ghost" onClick={draft}>
          生成声音合同草稿
        </button>
        <AgentBar slug={slug} station="sound" onDone={() => { load().catch(() => undefined); onChanged(); }} />
        {contract?.kinds ? <p className="dim">本集：{(contract.kinds || []).join(" / ")}</p> : null}
        {contract?.cues?.length ? (
          <table className="plain">
            <thead>
              <tr>
                <th>镜</th>
                <th>种类</th>
                <th>怎么念</th>
                <th>词</th>
              </tr>
            </thead>
            <tbody>
              {contract.cues.map((cue: any) => (
                <tr key={cue.id}>
                  <td>{cue.id}</td>
                  <td>{cue.kind_label}</td>
                  <td>{cue.intention}</td>
                  <td>{cue.line}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </details>
    </div>
  );
}
