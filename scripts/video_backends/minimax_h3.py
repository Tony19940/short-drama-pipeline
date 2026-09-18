"""MiniMax-H3 official API (v2). Hard first-frame image-to-video.

Docs: https://platform.minimaxi.com/docs/guides/video-generation
Create: POST {base}/v2/video_generation
Query:  GET  {base}/v2/query/video_generation/{task_id}

Official contract: first/last-frame I2V and multimodal reference are mutually
exclusive. This backend never mixes first_frame/last_frame with
reference_image. Identity for hard-frame shots lives in the locked still.
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import time
from pathlib import Path
from typing import Optional

import requests

ROOT = Path(__file__).resolve().parents[2]


def _truthy(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


class MiniMaxH3:
    def __init__(self, require_key: bool = True) -> None:
        self.api_key = os.environ.get("MINIMAX_API_KEY", "").strip()
        if require_key and not self.api_key:
            raise SystemExit("set MINIMAX_API_KEY")
        self.base = os.environ.get("MINIMAX_BASE_URL", "https://api.minimax.io").rstrip("/")
        self.model = os.environ.get("MINIMAX_MODEL", "MiniMax-H3").strip() or "MiniMax-H3"
        self.resolution = (os.environ.get("MINIMAX_RESOLUTION", "768P").strip() or "768P").upper()
        self.poll = int(os.environ.get("MINIMAX_POLL_SECONDS", "12"))
        self.watermark = _truthy("MINIMAX_AIGC_WATERMARK", "0")
        if self.model == "MiniMax-H3-Max":
            self.min_duration = 5
            self.max_duration = 15
            self.allowed_resolutions = {"480P", "768P"}
        else:
            self.min_duration = 4
            self.max_duration = 15
            self.allowed_resolutions = {"768P", "2K"}

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": "Bearer " + self.api_key,
            "Content-Type": "application/json",
        }

    def _data_url(self, image: Path) -> str:
        mime = mimetypes.guess_type(image.name)[0] or "image/jpeg"
        b64 = base64.b64encode(image.read_bytes()).decode("ascii")
        return "data:" + mime + ";base64," + b64

    def _image_item(self, image: Path, role: str) -> dict:
        return {
            "type": "image_url",
            "image_url": {"url": self._data_url(image)},
            "role": role,
        }

    def clamp_duration(self, seconds: int, shot_id: str = "") -> int:
        try:
            value = int(seconds or 0)
        except (TypeError, ValueError):
            value = 0
        if value < self.min_duration or value > self.max_duration:
            where = (shot_id + " ") if shot_id else ""
            raise RuntimeError(
                where + "秒数 " + str(value) + " 不在 " + self.model
                + " 档内 [" + str(self.min_duration) + "," + str(self.max_duration)
                + "]，改分镜表，不替人改"
            )
        return value

    def _normalize_resolution(self, resolution: Optional[str] = None) -> str:
        value = (resolution or self.resolution).strip().upper()
        aliases = {"768": "768P", "480": "480P"}
        value = aliases.get(value, value)
        if value not in self.allowed_resolutions:
            allowed = ", ".join(sorted(self.allowed_resolutions))
            raise RuntimeError(self.model + " 分辨率 " + value + " 不在 [" + allowed + "]")
        return value

    def estimate_cny(self, seconds: int, resolution: Optional[str] = None) -> float:
        res = self._normalize_resolution(resolution)
        duration = self.clamp_duration(seconds)
        if self.model == "MiniMax-H3-Max" and res == "480P":
            return round(0.33 * duration, 2)
        if res == "2K":
            return round(0.80 * duration, 2)
        return round(0.50 * duration, 2)

    def build_payload(
        self,
        image: Path,
        prompt: str,
        seconds: int,
        refs: list[Path] | None = None,
        mode: str = "i2v",
        last_frame: Path | None = None,
        resolution: Optional[str] = None,
    ) -> dict:
        if mode == "t2v":
            raise RuntimeError("H3 成片路径不能走文生视频")
        duration = self.clamp_duration(seconds)
        res = self._normalize_resolution(resolution)
        text = str(prompt or "").strip()
        if not text:
            raise RuntimeError("missing prompt")
        content: list[dict] = [{"type": "text", "text": text}]
        use_last = mode == "flf" and last_frame is not None and last_frame.exists()
        if mode == "r2v":
            refs_used = list(refs or [])[:9]
            if not refs_used:
                raise RuntimeError("r2v 需要 reference_image")
            for ref in refs_used:
                content.append(self._image_item(ref, "reference_image"))
        else:
            content.append(self._image_item(image, "first_frame"))
            if use_last:
                content.append(self._image_item(last_frame, "last_frame"))
        return {
            "model": self.model,
            "content": content,
            "duration": duration,
            "resolution": res,
            "aigc_watermark": self.watermark,
        }

    def _ticket_path(self, dest: Path) -> Path:
        return dest.with_suffix(dest.suffix + ".h3-task.json")

    def _read_ticket(self, dest: Path) -> dict:
        path = self._ticket_path(dest)
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_ticket(self, dest: Path, payload: dict) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        body = dict(payload)
        body["updated_at"] = int(time.time())
        self._ticket_path(dest).write_text(
            json.dumps(body, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _json_body(self, response: requests.Response) -> dict:
        if not (response.text or "").strip():
            return {}
        try:
            body = response.json()
        except ValueError:
            return {"error": {"message": (response.text or "")[:400]}}
        return body if isinstance(body, dict) else {"error": {"message": str(body)[:400]}}

    def _error_text(self, status: int, body: dict, raw: str = "") -> str:
        base = body.get("base_resp") if isinstance(body.get("base_resp"), dict) else {}
        err = body.get("error") if isinstance(body.get("error"), dict) else {}
        msg = (
            base.get("status_msg")
            or err.get("message")
            or body.get("message")
            or body.get("msg")
            or (raw or "")[:400]
            or json.dumps(body, ensure_ascii=False)[:400]
        )
        code = base.get("status_code") or err.get("code") or status
        return "MiniMax " + str(code) + ": " + str(msg)

    def submit(
        self,
        image: Path,
        prompt: str,
        seconds: int,
        refs: list[Path] | None = None,
        mode: str = "i2v",
        last_frame: Path | None = None,
    ) -> str:
        if not self.api_key:
            raise SystemExit("set MINIMAX_API_KEY")
        payload = self.build_payload(
            image, prompt, seconds, refs=refs, mode=mode, last_frame=last_frame
        )
        response = requests.post(
            self.base + "/v2/video_generation",
            headers=self._headers(),
            json=payload,
            timeout=120,
        )
        body = self._json_body(response)
        if response.status_code >= 400:
            raise RuntimeError(self._error_text(response.status_code, body, response.text))
        base = body.get("base_resp") if isinstance(body.get("base_resp"), dict) else {}
        if base.get("status_code") not in (0, None):
            raise RuntimeError(self._error_text(int(base.get("status_code") or 0), body, response.text))
        task_id = body.get("task_id") or (body.get("task") or {}).get("id")
        if not task_id:
            raise RuntimeError("MiniMax 没有返回 task_id: " + json.dumps(body, ensure_ascii=False)[:400])
        return str(task_id)

    def wait_url(self, task_id: str) -> str:
        url = self.base + "/v2/query/video_generation/" + task_id
        while True:
            time.sleep(self.poll)
            try:
                response = requests.get(url, headers=self._headers(), timeout=60)
            except requests.RequestException as exc:
                print("  poll retry: " + str(exc), flush=True)
                continue
            body = self._json_body(response)
            if response.status_code >= 400:
                raise RuntimeError(self._error_text(response.status_code, body, response.text))
            task = body.get("task") if isinstance(body.get("task"), dict) else body
            status = str(task.get("status") or "").lower()
            print("  " + task_id + " " + status, flush=True)
            if status in {"succeeded", "success"}:
                content = task.get("content") or {}
                download = content.get("url")
                if not download:
                    raise RuntimeError("成功但没有视频地址: " + json.dumps(task, ensure_ascii=False)[:400])
                return download
            if status in {"failed", "cancelled", "canceled"}:
                raise RuntimeError(task_id + " " + status + ": " + str(task.get("error") or task))

    def download(self, url: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        response = requests.get(url, timeout=180)
        response.raise_for_status()
        dest.write_bytes(response.content)

    def render(
        self,
        image: Path,
        prompt: str,
        seconds: int,
        dest: Path,
        refs: list[Path] | None = None,
        mode: str = "i2v",
        last_frame: Path | None = None,
        force: bool = False,
    ) -> None:
        dropped = bool(refs) and mode != "r2v"
        extra = (
            " refs=dropped (first_frame cannot mix with reference_image)"
            if dropped
            else " refs=" + str(len(refs or []))
        )
        print(
            "h3 " + dest.name + " (" + str(seconds) + "s) " + self.model
            + " " + self.resolution + " mode=" + mode + extra,
            flush=True,
        )
        if dropped:
            refs = []
        self.clamp_duration(seconds, shot_id=dest.stem)
        self._normalize_resolution()
        if not force and dest.exists() and dest.stat().st_size > 1024:
            print("  skip existing " + str(dest), flush=True)
            return
        ticket = {} if force else self._read_ticket(dest)
        task_id = "" if force else str(ticket.get("task_id") or "").strip()
        if not task_id:
            self._write_ticket(
                dest,
                {"status": "submitting", "dest": str(dest), "model": self.model, "base": self.base},
            )
            task_id = self.submit(
                image, prompt, seconds, refs=refs, mode=mode, last_frame=last_frame
            )
            self._write_ticket(
                dest,
                {
                    "task_id": task_id,
                    "status": "submitted",
                    "dest": str(dest),
                    "model": self.model,
                    "base": self.base,
                    "estimate_cny": self.estimate_cny(seconds),
                },
            )
            print("  task " + task_id, flush=True)
        else:
            print("  resume " + task_id, flush=True)
        url = self.wait_url(task_id)
        self._write_ticket(
            dest,
            {"task_id": task_id, "status": "succeeded", "url": url, "dest": str(dest)},
        )
        self.download(url, dest)
        print("  wrote " + str(dest), flush=True)


def _summarize_payload(payload: dict) -> dict:
    roles = [
        item.get("role")
        for item in payload.get("content") or []
        if item.get("type") == "image_url"
    ]
    text_item = next(
        (item for item in payload.get("content") or [] if item.get("type") == "text"),
        {},
    )
    prompt = str(text_item.get("text") or "")
    return {
        "model": payload.get("model"),
        "duration": payload.get("duration"),
        "resolution": payload.get("resolution"),
        "aigc_watermark": payload.get("aigc_watermark"),
        "image_roles": roles,
        "prompt_chars": len(prompt),
        "prompt_head": prompt[:180],
    }


def _shot_plan(prod: Path, shot_id: str) -> dict:
    from director.pipeline import read_artifact

    packages = read_artifact(prod, "gen_packages.json")
    pkg = next(
        (item for item in (packages.get("packages") or []) if item.get("shot_id") == shot_id),
        None,
    )
    if not pkg:
        raise SystemExit("没有这个镜头的生成包：" + shot_id)
    frames = read_artifact(prod, "keyframes.json")
    kf = next(
        (item for item in (frames.get("keyframes") or []) if item.get("shot_id") == shot_id),
        {},
    )
    first_rel = str(kf.get("first_frame_file") or ("04-frames/" + shot_id + ".jpg"))
    last_rel = str(kf.get("last_frame_file") or "")
    gen_mode = str(pkg.get("gen_mode") or "i2v_first")
    mode = "flf" if gen_mode == "flf2v" else "i2v"
    return {
        "shot_id": shot_id,
        "prompt": str(pkg.get("motion_prompt") or "").strip(),
        "seconds": int(round(float(pkg.get("duration_sec") or 4))),
        "first_rel": first_rel,
        "last_rel": last_rel if mode == "flf" else "",
        "mode": mode,
        "gen_mode": gen_mode,
    }


def main() -> None:
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    from director.paths import load_dotenv

    load_dotenv()
    parser = argparse.ArgumentParser(description="Official MiniMax-H3 I2V (no CompShare hijack)")
    parser.add_argument("--check", action="store_true", help="print config; do not submit")
    parser.add_argument("--dry-run", action="store_true", help="print payload summary; do not submit")
    parser.add_argument("--prod", help="productions/<slug>")
    parser.add_argument("--shot", help="e.g. SH027; reads gen_packages.json")
    parser.add_argument("--image")
    parser.add_argument("--last")
    parser.add_argument("--prompt")
    parser.add_argument("--seconds", type=int)
    parser.add_argument("--dest")
    parser.add_argument("--mode", choices=["i2v", "flf"], default="i2v")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    backend = MiniMaxH3(require_key=not (args.check or args.dry_run))
    print(
        json.dumps(
            {
                "model": backend.model,
                "base": backend.base,
                "resolution": backend.resolution,
                "key": "set" if backend.api_key else "missing",
                "duration": [backend.min_duration, backend.max_duration],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    if args.check:
        return

    image: Optional[Path] = Path(args.image) if args.image else None
    last: Optional[Path] = Path(args.last) if args.last else None
    prompt = str(args.prompt or "").strip()
    seconds = args.seconds
    mode = args.mode
    dest: Optional[Path] = Path(args.dest) if args.dest else None
    shot_id = str(args.shot or "").strip()

    if args.prod and shot_id:
        prod = Path(args.prod)
        if not prod.is_absolute():
            prod = (ROOT / prod).resolve()
        plan = _shot_plan(prod, shot_id)
        image = image or (prod / plan["first_rel"])
        if plan["last_rel"]:
            last = last or (prod / plan["last_rel"])
        prompt = prompt or plan["prompt"]
        seconds = int(seconds if seconds is not None else plan["seconds"])
        if args.mode == "i2v" and plan["mode"] == "flf":
            mode = plan["mode"]
        dest = dest or (prod / "05-shots" / "smoke-h3" / (shot_id + ".mp4"))
    if image is None or not prompt or seconds is None:
        raise SystemExit("need --image/--prompt/--seconds, or --prod plus --shot")
    if not image.exists():
        raise SystemExit("missing first frame " + str(image))
    if last is not None and not last.exists():
        raise SystemExit("missing last frame " + str(last))
    dest = dest or Path("h3-smoke.mp4")
    payload = backend.build_payload(image, prompt, int(seconds), mode=mode, last_frame=last)
    summary = _summarize_payload(payload)
    summary["image"] = str(image)
    summary["last"] = str(last) if last else None
    summary["dest"] = str(dest)
    summary["estimate_cny"] = backend.estimate_cny(int(seconds))
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    if args.dry_run:
        print("dry-run only; no MiniMax task submitted", flush=True)
        return
    backend.render(
        image,
        prompt,
        int(seconds),
        dest,
        mode=mode,
        last_frame=last,
        force=args.force,
    )


if __name__ == "__main__":
    main()
