import { useEffect, useState } from "react";
import { get } from "../api";
import { StagePage } from "./StagePage";
import { ShotsPage } from "./ShotsPage";
import { ShotTablePage } from "./ShotTablePage";

export function DirectorPage({
  slug,
  onChanged,
}: {
  slug: string;
  gate?: any;
  previous?: any;
  onChanged: () => void;
}) {
  const [phase, setPhase] = useState<"stage" | "shots">("stage");
  const [pipeline, setPipeline] = useState<any>(null);
  // null = follow what the production uses; the pill lets a person override for this session
  const [view, setView] = useState<"v2" | "legacy" | null>(null);

  function loadPipeline() {
    get(`/api/productions/${slug}/pipeline`)
      .then(setPipeline)
      .catch(() => setPipeline(null));
  }

  useEffect(() => {
    setView(null);
    setPipeline(null);
    loadPipeline();
  }, [slug]);

  const v2 = Boolean(pipeline?.uses_pipeline || pipeline?.artifacts?.shot_list?.exists);
  const showV2 = view ? view === "v2" : v2;

  function changed() {
    loadPipeline();
    onChanged();
  }

  return (
    <div className="flow-main">
      <div className="subpath">
        <button className={phase === "stage" ? "on" : ""} onClick={() => setPhase("stage")}>
          1 舞台
        </button>
        <button className={phase === "shots" ? "on" : ""} onClick={() => setPhase("shots")}>
          2 镜头表
        </button>
      </div>
      {phase === "stage" ? (
        <>
          <StagePage slug={slug} onChanged={onChanged} />
          <div className="toolbar">
            <button className="danger" onClick={() => setPhase("shots")}>
              舞台好了，去选镜头
            </button>
          </div>
        </>
      ) : (
        <>
          <div className="toolbar">
            <button className="pill" onClick={() => setView(showV2 ? "legacy" : "v2")}>
              {showV2 ? "旧表 shots.json" : "镜头表 v2"}
            </button>
            <span className="dim">
              {showV2
                ? v2
                  ? "读 .pipeline/shot_list.json。"
                  : "这部戏还没用流水线；从空表开始，先场戏分析再拆镜。"
                : "旧表 shots.json。"}
            </span>
          </div>
          {showV2 ? <ShotTablePage slug={slug} onChanged={changed} /> : <ShotsPage slug={slug} onChanged={changed} />}
        </>
      )}
    </div>
  );
}
