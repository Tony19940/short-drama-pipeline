import { useEffect, useState } from "react";
import { get } from "../api";
import { FramesPage } from "./FramesPage";
import { RenderPage } from "./RenderPage";

export function CameraPage({
  slug,
  gate,
  onChanged,
}: {
  slug: string;
  gate?: any;
  previous?: any;
  onChanged: () => void;
}) {
  const [caps, setCaps] = useState<any>(null);
  const [phase, setPhase] = useState<"frames" | "render">("frames");
  useEffect(() => {
    get(`/api/gpu`).then(setCaps).catch(() => undefined);
  }, [slug]);
  return (
    <div className="flow-main">
      <div className="subpath">
        <button className={phase === "frames" ? "on" : ""} onClick={() => setPhase("frames")}>
          1 锁首帧
        </button>
        <button className={phase === "render" ? "on" : ""} onClick={() => setPhase("render")}>
          2 派出成片
        </button>
      </div>
      {caps && caps.backend === "seedance" ? (
        <p className="ok">Seedance 2.0 Mini 已接火山方舟，按镜派出图生视频。</p>
      ) : caps && !caps.gpu && !caps.ok ? (
        <p className="warn">未接 GPU，也没有 ARK_API_KEY，派出后会停在排队。</p>
      ) : null}
      {caps && caps.backend !== "seedance" && !caps.ref2va_installed ? (
        <p className="dim">Ref2VA 未安装，只用锁定首帧 FL2VA，不要冒充。</p>
      ) : null}
      {gate?.stale ? <p className="warn">上游改过了，重审前不能派出。</p> : null}
      {phase === "frames" ? (
        <>
          <FramesPage slug={slug} onChanged={onChanged} />
          <div className="toolbar">
            <button className="danger" onClick={() => setPhase("render")}>
              首帧齐了，去派出
            </button>
          </div>
        </>
      ) : (
        <RenderPage slug={slug} onChanged={onChanged} />
      )}
    </div>
  );
}
