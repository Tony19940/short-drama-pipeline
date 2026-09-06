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

  const contract = sound?.official || sound?.draft || sound?.live;
  return (
    <div className="flow-main">
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
