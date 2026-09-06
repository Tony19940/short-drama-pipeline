import { useEffect, useState } from "react";
import { get, post } from "../api";

export function ReviewPage({ slug, onChanged }: { slug: string; onChanged: () => void }) {
  const [shots, setShots] = useState<any>(null);
  const [contract, setContract] = useState<any>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const cut = `/media/${slug}/06-export/ep01.mp4`;
  const preview = `/media/${slug}/06-export/preview-vo.mp4`;
  const partial = `/media/${slug}/06-export/preview-partial-vo.mp4`;

  async function load() {
    setShots(await get(`/api/productions/${slug}/shots`));
    setContract(await get(`/api/productions/${slug}/review-contract`).catch(() => null));
  }
  useEffect(() => {
    load().catch((err) => setError(err.message));
    const timer = setInterval(() => load().catch(() => undefined), 4000);
    return () => clearInterval(timer);
  }, [slug]);

  async function review() {
    setBusy("review");
    setError("");
    try {
      await post(`/api/productions/${slug}/review`, {});
      await load();
      onChanged();
    } catch (err: any) {
      setError(err.message);
      await load();
    } finally {
      setBusy("");
    }
  }

  async function assemble() {
    setBusy("assemble");
    setError("");
    try {
      await post(`/api/productions/${slug}/assemble`, {});
      onChanged();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  if (!shots) return <p className="dim">读取成片…</p>;
  const ready = shots.shots.filter((s: any) => s.video_exists).length;
  return (
    <section className="card pad path-card">
      <h2>听这一集</h2>
      <p>
        {ready} / {shots.shots.length} 条已有视频
      </p>
      {error ? <p className="err">{error}</p> : null}
      <video key={cut} src={cut} controls style={{ width: "min(360px, 100%)", background: "#000" }} />
      <div className="toolbar">
        <button className="danger" disabled={!!busy} onClick={review}>
          {busy === "review" ? "叠旁白中…" : "叠工作旁白"}
        </button>
      </div>
      {contract?.verdict ? (
        <p className={contract.verdict === "REVISE" ? "warn" : "ok"}>
          审片 {contract.verdict} · 脚本 {contract.required || "—"} · 画面 {contract.visual || "还要人看"}
        </p>
      ) : (
        <p className="dim">先叠旁白，再听一遍对不齐的地方。</p>
      )}
      {(contract?.failures || []).length ? (
        <ul>
          {(contract.failures || []).map((item: string) => (
            <li key={item} className="bad">
              {item}
            </li>
          ))}
        </ul>
      ) : null}
      <details className="soft">
        <summary>旧预览、只拼画面、分镜成绩</summary>
        <div className="toolbar">
          <button className="ghost" disabled={!!busy} onClick={assemble}>
            {busy === "assemble" ? "拼接中…" : "只拼画面"}
          </button>
        </div>
        <p className="dim">旧工作旁白</p>
        <video key={preview} src={preview} controls style={{ width: "min(280px, 100%)", background: "#000" }} />
        <p className="dim">部分旁白</p>
        <video src={partial} controls style={{ width: "min(280px, 100%)", background: "#000" }} />
        {(contract?.shot_verdicts || []).map((item: any) => (
          <div key={item.id} className="dim">
            {item.id}: {item.grade}
            {(item.s0 || []).length ? ` · ${(item.s0 || []).join("；")}` : ""}
          </div>
        ))}
      </details>
    </section>
  );
}
