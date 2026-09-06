import { useState } from "react";
import { StagePage } from "./StagePage";
import { ShotsPage } from "./ShotsPage";

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
  return (
    <div className="flow-main">
      <div className="subpath">
        <button className={phase === "stage" ? "on" : ""} onClick={() => setPhase("stage")}>
          1 舞台
        </button>
        <button className={phase === "shots" ? "on" : ""} onClick={() => setPhase("shots")}>
          2 镜头清单
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
        <ShotsPage slug={slug} onChanged={onChanged} />
      )}
    </div>
  );
}
