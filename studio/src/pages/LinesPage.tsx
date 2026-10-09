import { useEffect, useState } from "react";
import { get } from "../api";

const REVIEW = "01-bible/lines-review.html";

export function LinesPage({ slug }: { slug: string }) {
  const [stamp, setStamp] = useState(Date.now());
  const [lines, setLines] = useState<any>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    get(`/api/productions/${slug}/pipeline/lines.json`)
      .then((data) => setLines(data))
      .catch((err: any) => setError(err.message || String(err)));
  }, [slug, stamp]);

  const rows = lines?.lines || [];
  return (
    <div className="flow-main">
      <p className="dim">
        中文是工作稿，高棉语是成片稿（Gemini 按说话人、听话人、语体写）。先读盲听稿，再对照中文和高棉语逐字回译；
        镜头要装得下中文原声和高棉语配音里较长的那个。审完签字后才能进分镜。
      </p>
      <p className="dim">
        更新：<code>python3 scripts/build_lines.py --prod productions/{slug} --episode 1 --khmer --tighten --html</code>
      </p>
      {error ? <p className="err">{error}</p> : null}
      {lines ? (
        <p className="dim">
          {rows.length} 句 · 状态 {lines.status || "draft"}
          {lines.reviewed_by ? ` · 审核 ${lines.reviewed_by}` : ""}
          <button className="ghost compact" onClick={() => setStamp(Date.now())}>刷新</button>
        </p>
      ) : null}
      <iframe
        key={stamp}
        title="台词表"
        src={`/media/${slug}/${REVIEW}?t=${stamp}`}
        style={{ width: "100%", height: "75vh", border: "1px solid var(--line, #ddd)", borderRadius: 10 }}
      />
    </div>
  );
}
