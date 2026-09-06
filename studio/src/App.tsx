import { useEffect, useMemo, useState } from "react";
import { get, post } from "./api";
import { AssetsPage } from "./pages/AssetsPage";
import { BiblePage } from "./pages/BiblePage";
import { CutPage } from "./pages/CutPage";
import { DirectorPage } from "./pages/DirectorPage";
import { EditPage } from "./pages/EditPage";
import { FramesPage } from "./pages/FramesPage";
import { PackagePage } from "./pages/PackagePage";
import { RenderPage } from "./pages/RenderPage";
import { SpecPage } from "./pages/SpecPage";
import { StoryPage } from "./pages/StoryPage";
import { Guide } from "./Guide";

const TABS = [
  { id: "story", label: "小说", now: "写或上传故事。这里不写镜头。" },
  { id: "writer", label: "编剧", now: "改成能拍的分场本，台词在这里定稿。" },
  { id: "art", label: "资产", now: "锁脸、空镜、道具。资产不是某一镜。" },
  { id: "design", label: "分镜", now: "决定拍哪些镜头、左右和覆盖。不写提示词。" },
  { id: "spec", label: "说明书", now: "把每一镜写成 7 组给人看的说明。" },
  { id: "package", label: "生成包", now: "翻译成模型计划。人确认后才能出图出片。" },
  { id: "frames", label: "关键帧", now: "按这一镜构图出静帧，过审后再出视频。" },
  { id: "render", label: "视频", now: "用过审首帧出单镜。未确认的生成包不能派。" },
  { id: "sound", label: "声音", now: "只念编剧原句，叠旁白听一遍。" },
  { id: "edit", label: "剪辑", now: "按时间线剪，不要整段拼接。" },
] as const;

type Gate = {
  id: string;
  label: string;
  tab: string;
  ready: boolean;
  locked: boolean;
  stale?: boolean;
  status?: string;
  status_label?: string;
  reason: string;
  previous_locked?: boolean;
  virtual?: boolean;
  migrated?: boolean;
};

function pickTab(gates: Gate[]): (typeof TABS)[number]["id"] {
  const stale = gates.find((g) => g.stale);
  if (stale) return stale.tab as (typeof TABS)[number]["id"];
  const open = gates.find((g) => !g.locked);
  if (open) return open.tab as (typeof TABS)[number]["id"];
  return "edit";
}


function RejectBar({
  slug,
  currentId,
  onDone,
}: {
  slug: string;
  currentId?: string;
  onDone: () => void;
}) {
  const [target, setTarget] = useState("C");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  async function send() {
    if (!reason.trim()) return;
    setBusy(true);
    try {
      await post(`/api/productions/${slug}/pipeline/reject`, {
        fromAgent: currentId,
        sendBackTo: target,
        reason,
      });
      setReason("");
      onDone();
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="reject-bar">
      <select value={target} onChange={(e) => setTarget(e.target.value)}>
        <option value="0">打回小说</option>
        <option value="A">打回编剧</option>
        <option value="B">打回资产</option>
        <option value="C">打回分镜</option>
        <option value="C1">打回说明书</option>
        <option value="C2">打回生成包</option>
        <option value="D">打回关键帧</option>
        <option value="E">打回视频</option>
      </select>
      <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="证据 / 为什么打回" />
      <button className="ghost compact" disabled={busy || !reason.trim()} onClick={send}>
        {busy ? "…" : "打回"}
      </button>
    </div>
  );
}

export function App() {
  const [productions, setProductions] = useState<any[]>([]);
  const [slug, setSlug] = useState("004-yuye-jinlian");
  const [tab, setTab] = useState<(typeof TABS)[number]["id"]>("story");
  const [landed, setLanded] = useState("");
  const [prod, setProd] = useState<any>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [newId, setNewId] = useState("");
  const [newTitle, setNewTitle] = useState("");
  const [showNew, setShowNew] = useState(false);
  const [diff, setDiff] = useState<any>(null);
  const [more, setMore] = useState(false);

  async function refreshList() {
    const data = await get("/api/productions");
    setProductions(data.productions || []);
  }

  async function refresh() {
    const data = await get(`/api/productions/${slug}`);
    setProd(data);
    return data;
  }

  useEffect(() => {
    refreshList().catch((err) => setError(String(err.message || err)));
  }, []);

  useEffect(() => {
    setLanded("");
    setDiff(null);
    setMore(false);
    refresh().catch((err) => setError(String(err.message || err)));
  }, [slug]);

  const gates: Gate[] = prod?.gates?.gates || [];
  useEffect(() => {
    if (!gates.length || landed === slug) return;
    setTab(pickTab(gates));
    setLanded(slug);
  }, [gates, landed, slug]);

  useEffect(() => {
    setMore(false);
    setDiff(null);
  }, [tab]);

  const currentGate = useMemo(() => gates.find((g) => g.tab === tab), [gates, tab]);
  const tabIndex = TABS.findIndex((item) => item.id === tab);
  const nextTab = tabIndex >= 0 && tabIndex < TABS.length - 1 ? TABS[tabIndex + 1] : null;
  const prevTab = tabIndex > 0 ? TABS[tabIndex - 1] : null;
  const title = productions.find((item) => item.id === slug)?.name || slug;
  const guide = TABS.find((item) => item.id === tab);

  async function lockGate(locked: boolean) {
    if (!currentGate) return;
    setBusy(true);
    setError("");
    try {
      await post(`/api/productions/${slug}/gates/lock`, {
        gateId: currentGate.id,
        locked,
      });
      await refresh();
    } catch (err: any) {
      setError(err.message || String(err));
      throw err;
    } finally {
      setBusy(false);
    }
  }

  async function primary() {
    if (!currentGate) return;
    try {
      if (currentGate.stale || !currentGate.locked) {
        await lockGate(true);
      }
      if (nextTab) setTab(nextTab.id);
    } catch {
      /* error already set */
    }
  }

  async function showDiff() {
    if (!currentGate) return;
    try {
      setDiff(await get(`/api/productions/${slug}/diff?gateId=${encodeURIComponent(currentGate.id)}`));
      setMore(true);
    } catch (err: any) {
      setError(err.message || String(err));
    }
  }

  async function createProd() {
    if (!newId.trim()) return;
    setBusy(true);
    setError("");
    try {
      const created = await post("/api/productions", { id: newId.trim(), title: newTitle.trim() });
      await refreshList();
      setSlug(created.id);
      setTab("story");
      setLanded(created.id);
      setNewId("");
      setNewTitle("");
      setShowNew(false);
    } catch (err: any) {
      setError(err.message || String(err));
    } finally {
      setBusy(false);
    }
  }

  const primaryLabel = currentGate?.stale
    ? "重审并进入下一步"
    : currentGate?.locked
      ? nextTab
        ? `下一步：${nextTab.label}`
        : "已是最后一步"
      : nextTab
        ? `锁定，进入${nextTab.label}`
        : "锁定本关";
  const primaryDisabled =
    busy ||
    (!currentGate?.locked && !currentGate?.previous_locked && currentGate?.id !== "0") ||
    (currentGate?.locked && !currentGate?.stale && !nextTab);

  const showReason = Boolean(
    currentGate?.reason && (currentGate.stale || (!currentGate.locked && currentGate.status !== "locked")),
  );

  return (
    <div className="app">
      <header className="chrome">
        <div className="topbar">
          <div className="brand">
            导演台 · <span>{title}</span>
          </div>
          <div className="meta">
            <select value={slug} onChange={(e) => setSlug(e.target.value)}>
              {productions.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name || item.id}
                </option>
              ))}
            </select>
            <button className="ghost compact" onClick={() => setShowNew((v) => !v)}>
              {showNew ? "取消" : "新建"}
            </button>
            {showNew ? (
              <div className="new-box">
                <input value={newId} onChange={(e) => setNewId(e.target.value)} placeholder="项目 id" />
                <input value={newTitle} onChange={(e) => setNewTitle(e.target.value)} placeholder="标题" />
                <button className="danger compact" disabled={busy} onClick={createProd}>
                  创建
                </button>
              </div>
            ) : null}
            <span className={prod?.video_ready || prod?.gpu ? "ok" : "dim"}>
              {prod?.video_backend === "seedance"
                ? "Seedance"
                : prod?.gpu
                  ? "GPU"
                  : prod?.video_ready
                    ? "可出片"
                    : "未接出片"}
            </span>
          </div>
        </div>
        <nav className="pathrail" aria-label="制片路径">
        {TABS.map((item, index) => {
          const gate = gates.find((g) => g.tab === item.id);
          const state = gate?.stale ? "stale" : gate?.locked ? "done" : tab === item.id ? "now" : "todo";
          return (
            <button
              key={item.id}
              className={`step ${tab === item.id ? "on" : ""} ${state}`}
              onClick={() => setTab(item.id)}
            >
              <i>{index + 1}</i>
              {item.label}
            </button>
          );
        })}
        </nav>
      </header>
      <main className="page">
        {guide ? <Guide now={currentGate?.stale ? `上游改过了，先重审${guide.label}。` : guide.now} /> : null}
        {error ? <p className="err">{error}</p> : null}
        {showReason ? (
          <p className={`status ${currentGate?.stale ? "warn" : currentGate?.ready ? "warn" : "dim"}`}>{currentGate?.reason}</p>
        ) : null}
        {diff && more ? (
          <pre className="dim">
            改动：{(diff.changed || []).join("、") || "无"}
            {"\n"}上游：{(diff.upstream_changed || []).join("、") || "无"}
          </pre>
        ) : null}
        {tab === "story" ? <StoryPage slug={slug} gate={currentGate} onChanged={refresh} /> : null}
        {tab === "writer" ? <BiblePage slug={slug} onChanged={refresh} /> : null}
        {tab === "art" ? <AssetsPage slug={slug} onChanged={refresh} /> : null}
        {tab === "design" ? <DirectorPage slug={slug} gate={currentGate} onChanged={refresh} /> : null}
        {tab === "spec" ? <SpecPage slug={slug} onChanged={refresh} /> : null}
        {tab === "package" ? <PackagePage slug={slug} onChanged={refresh} /> : null}
        {tab === "frames" ? <FramesPage slug={slug} onChanged={refresh} /> : null}
        {tab === "render" ? <RenderPage slug={slug} onChanged={refresh} /> : null}
        {tab === "sound" ? <EditPage slug={slug} gate={currentGate} onChanged={refresh} /> : null}
        {tab === "edit" ? <CutPage slug={slug} gate={currentGate} onChanged={refresh} /> : null}
      </main>
      <footer className="pathfoot">
        <div className="pathfoot-row">
          <button className="ghost compact" disabled={!prevTab} onClick={() => prevTab && setTab(prevTab.id)}>
            {prevTab ? `上一步 ${prevTab.label}` : "开始"}
          </button>
          <button className="ghost compact" onClick={() => setMore((v) => !v)}>
            {more ? "收起" : "更多"}
          </button>
          <button className="danger" disabled={primaryDisabled} onClick={primary}>
            {busy ? "…" : primaryLabel}
          </button>
        </div>
        {more ? (
          <div className="more-row">
            <button className="ghost compact" disabled={busy} onClick={showDiff}>
              查看差异
            </button>
            {currentGate?.locked ? (
              <button className="ghost compact" disabled={busy} onClick={() => lockGate(false).catch(() => undefined)}>
                退回本关
              </button>
            ) : null}
            <RejectBar slug={slug} currentId={currentGate?.id} onDone={refresh} />
          </div>
        ) : null}
      </footer>
    </div>
  );
}
