import { useState } from "react";
import { post } from "./api";

const LABELS: Record<string, string> = {
  novel: "让小说 Agent 起草",
  writer: "让编剧 Agent 改编",
  assets: "让资产 Agent 写锁定卡",
  design: "让导演 Agent 拆镜",
  spec: "让说明书 Agent 写 7 组",
  package: "让生成包 Agent 翻译计划",
  sound: "让声音 Agent 对齐台词",
  edit: "让剪辑 Agent 出时间线",
};

export function AgentBar({
  slug,
  station,
  onDone,
}: {
  slug: string;
  station: string;
  onDone?: (result?: any) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  async function run() {
    setBusy(true);
    setError("");
    setNote("");
    try {
      const result = await post(`/api/productions/${slug}/agents/${station}`, {});
      setNote(result.used_tokens ? "已起草，还没锁定。" : result.note || "已起草");
      onDone?.(result);
    } catch (err: any) {
      setError(err.message || String(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="agent-bar">
      <button className="danger" disabled={busy} onClick={run}>
        {busy ? "本岗 Agent 工作中…" : LABELS[station] || "让本岗 Agent 起草"}
      </button>
      <span className="dim">只写本岗交接。人审后再锁定。没有密钥不会装懂。</span>
      {note ? <p className="ok">{note}</p> : null}
      {error ? <p className="err">{error}</p> : null}
    </div>
  );
}
