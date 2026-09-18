"""Alibaba Bailian Wan 3.0 video (cn-beijing workspace host).

Docs: https://help.aliyun.com/zh/model-studio/wan3-video-generation-api-reference
Create: POST {base}/services/aigc/video-generation/video-synthesis
Query:  GET  {base}/tasks/{task_id}

Hard first-frame / first-last-frame cannot mix with reference_image.
Identity for hard-frame shots lives in the locked still. Text-to-video
is not a finish path.
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


class Wan3:
    def __init__(self, require_key: bool = True) -> None:
        self.api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
        if require_key and not self.api_key:
            raise SystemExit("set DASHSCOPE_API_KEY")
        workspace = os.environ.get("DASHSCOPE_WORKSPACE_ID", "").strip()
        region = os.environ.get("DASHSCOPE_REGION", "cn-beijing").strip() or "cn-beijing"
        default_base = (
            "https://" + workspace + "." + region + ".maas.aliyuncs.com/api/v1"
            if workspace
            else "https://dashscope.aliyuncs.com/api/v1"
        )
        self.base = os.environ.get("DASHSCOPE_BASE_URL", default_base).rstrip("/")
        self.model = os.environ.get("WAN_MODEL", "wan3.0-video").strip() or "wan3.0-video"
        self.resolution = (os.environ.get("WAN_RESOLUTION", "720P").strip() or "720P").upper()
        self.ratio = os.environ.get("WAN_RATIO", "adaptive").strip() or "adaptive"
        self.poll = int(os.environ.get("WAN_POLL_SECONDS", "8"))
        self.audio = _truthy("WAN_AUDIO", "0")
        self.prompt_extend = _truthy("WAN_PROMPT_EXTEND", "0")
        self.watermark = _truthy("WAN_WATERMARK", "0")
        self.min_duration = 2
        self.max_duration = 30
        self.allowed_resolutions = {"480P", "720P", "1080P"}
        self.allowed_models = {"wan3.0-video", "wan3.0-video-prime"}

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": "Bearer " + self.api_key,
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
            "X-DashScope-OssResourceResolve": "enable",
        }

    def _upload_host(self) -> str:
        return os.environ.get("DASHSCOPE_UPLOAD_URL", "https://dashscope.aliyuncs.com/api/v1/uploads").strip()

    def _use_oss(self) -> bool:
        return _truthy("WAN_UPLOAD_OSS", "1")

    def _data_url(self, image: Path) -> str:
        mime = mimetypes.guess_type(image.name)[0] or "image/jpeg"
        b64 = base64.b64encode(image.read_bytes()).decode("ascii")
        return "data:" + mime + ";base64," + b64

    def _oss_hosts(self, upload_host: str) -> list[str]:
        host = str(upload_host or "").rstrip("/")
        hosts: list[str] = []
        if "oss-cn-beijing.aliyuncs.com" in host:
            hosts.append(host.replace("oss-cn-beijing.aliyuncs.com", "oss-accelerate.aliyuncs.com"))
        if host:
            hosts.append(host)
        out: list[str] = []
        for item in hosts:
            if item not in out:
                out.append(item)
        return out

    def _oss_url(self, image: Path) -> str:
        import hashlib
        content = image.read_bytes()
        digest = hashlib.sha1(content).hexdigest()[:12]
        cache_key = digest + (image.suffix.lower() or ".jpg")
        cached = getattr(self, "_oss_cache", {}).get(cache_key)
        if cached:
            return cached
        policy_resp = requests.get(
            self._upload_host(),
            headers={"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"},
            params={"action": "getPolicy", "model": self.model},
            timeout=60,
        )
        if policy_resp.status_code >= 400:
            raise RuntimeError("Wan upload policy " + str(policy_resp.status_code) + ": " + policy_resp.text[:400])
        body = policy_resp.json() if policy_resp.text else {}
        data = body.get("data") if isinstance(body, dict) else {}
        if not isinstance(data, dict) or not data.get("upload_host"):
            raise RuntimeError("Wan upload policy 没有 upload_host: " + str(body)[:400])
        suffix = image.suffix.lower() or ".jpg"
        key = str(data.get("upload_dir") or "dashscope-instant") + "/" + image.stem + "-" + digest + suffix
        mime = mimetypes.guess_type(image.name)[0] or "image/jpeg"
        files = {
            "OSSAccessKeyId": (None, data["oss_access_key_id"]),
            "Signature": (None, data["signature"]),
            "policy": (None, data["policy"]),
            "x-oss-object-acl": (None, data["x_oss_object_acl"]),
            "x-oss-forbid-overwrite": (None, data["x_oss_forbid_overwrite"]),
            "key": (None, key),
            "success_action_status": (None, "200"),
            "file": (image.name, content, mime),
        }
        errors: list[str] = []
        for host in self._oss_hosts(str(data["upload_host"])):
            try:
                up = requests.post(host, files=files, timeout=30)
            except requests.RequestException as exc:
                errors.append(host.split("//")[-1].split("/")[0] + " " + type(exc).__name__)
                continue
            if up.status_code in {200, 204, 409}:
                oss_url = "oss://" + key
                self._oss_cache = getattr(self, "_oss_cache", {})
                self._oss_cache[cache_key] = oss_url
                print("  oss " + image.name + " via " + host.split("//")[-1].split("/")[0], flush=True)
                return oss_url
            errors.append(host.split("//")[-1].split("/")[0] + " HTTP " + str(up.status_code))
        raise RuntimeError("Wan OSS upload failed: " + "; ".join(errors)[:400])

    def _media_url(self, image: Path) -> str:
        if self._use_oss():
            return self._oss_url(image)
        return self._data_url(image)

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
        aliases = {"720": "720P", "480": "480P", "1080": "1080P"}
        value = aliases.get(value, value)
        if value not in self.allowed_resolutions:
            allowed = ", ".join(sorted(self.allowed_resolutions))
            raise RuntimeError(self.model + " 分辨率 " + value + " 不在 [" + allowed + "]")
        return value

    def _normalize_model(self) -> str:
        if self.model not in self.allowed_models:
            allowed = ", ".join(sorted(self.allowed_models))
            raise RuntimeError("Wan 模型 " + self.model + " 不在 [" + allowed + "]")
        return self.model

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
            raise RuntimeError("Wan 成片路径不能走文生视频")
        duration = self.clamp_duration(seconds)
        res = self._normalize_resolution(resolution)
        model = self._normalize_model()
        text = str(prompt or "").strip()
        if not text:
            raise RuntimeError("missing prompt")
        media: list[dict] = []
        if mode == "r2v":
            refs_used = list(refs or [])[:10]
            if not refs_used:
                raise RuntimeError("r2v 需要 reference_image")
            for ref in refs_used:
                media.append({"type": "reference_image", "url": self._media_url(ref)})
        else:
            media.append({"type": "first_frame", "url": self._media_url(image)})
            use_last = mode == "flf" and last_frame is not None and last_frame.exists()
            if use_last:
                media.append({"type": "last_frame", "url": self._media_url(last_frame)})
        return {
            "model": model,
            "input": {"prompt": text, "media": media},
            "parameters": {
                "resolution": res,
                "ratio": "adaptive" if mode in {"i2v", "flf"} else self.ratio,
                "duration": duration,
                "audio": self.audio,
                "prompt_extend": self.prompt_extend,
                "watermark": self.watermark,
            },
        }

    def _ticket_path(self, dest: Path) -> Path:
        return dest.with_suffix(dest.suffix + ".wan-task.json")

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
            return {"message": (response.text or "")[:400]}
        return body if isinstance(body, dict) else {"message": str(body)[:400]}

    def _error_text(self, status: int, body: dict, raw: str = "") -> str:
        output = body.get("output") if isinstance(body.get("output"), dict) else {}
        msg = (
            body.get("message")
            or output.get("message")
            or body.get("code")
            or (raw or "")[:400]
            or json.dumps(body, ensure_ascii=False)[:400]
        )
        code = body.get("code") or output.get("code") or status
        return "Wan " + str(code) + ": " + str(msg)

    def _video_url(self, body: dict) -> str:
        output = body.get("output") if isinstance(body.get("output"), dict) else {}
        results = output.get("results") if isinstance(output.get("results"), list) else []
        first = results[0] if results and isinstance(results[0], dict) else {}
        url = (
            output.get("video_url")
            or output.get("output_video_url")
            or first.get("url")
            or body.get("video_url")
        )
        return str(url or "").strip()

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
            raise SystemExit("set DASHSCOPE_API_KEY")
        payload = self.build_payload(
            image, prompt, seconds, refs=refs, mode=mode, last_frame=last_frame
        )
        response = requests.post(
            self.base + "/services/aigc/video-generation/video-synthesis",
            headers=self._headers(),
            json=payload,
            timeout=300,
        )
        body = self._json_body(response)
        if response.status_code >= 400:
            raise RuntimeError(self._error_text(response.status_code, body, response.text))
        output = body.get("output") if isinstance(body.get("output"), dict) else {}
        task_id = output.get("task_id") or body.get("task_id")
        if not task_id:
            raise RuntimeError("Wan 没有返回 task_id: " + json.dumps(body, ensure_ascii=False)[:400])
        return str(task_id)

    def wait_url(self, task_id: str) -> str:
        url = self.base + "/tasks/" + task_id
        headers = {"Authorization": "Bearer " + self.api_key}
        deadline = time.time() + int(os.environ.get("WAN_MAX_WAIT_SECONDS", "900"))
        while True:
            if time.time() > deadline:
                raise RuntimeError("Wan wait timeout " + task_id)
            time.sleep(self.poll)
            try:
                response = requests.get(url, headers=headers, timeout=60)
            except requests.RequestException as exc:
                print("  poll retry: " + str(exc), flush=True)
                continue
            body = self._json_body(response)
            if response.status_code >= 400:
                raise RuntimeError(self._error_text(response.status_code, body, response.text))
            output = body.get("output") if isinstance(body.get("output"), dict) else body
            status = str(output.get("task_status") or output.get("status") or "").upper()
            print("  " + task_id + " " + status, flush=True)
            if status in {"SUCCEEDED", "SUCCESS", "COMPLETED"}:
                download = self._video_url(body)
                if not download:
                    raise RuntimeError("成功但没有视频地址: " + json.dumps(body, ensure_ascii=False)[:400])
                return download
            if status in {"FAILED", "CANCELED", "CANCELLED", "UNKNOWN"}:
                raise RuntimeError(self._error_text(response.status_code, body, json.dumps(body, ensure_ascii=False)[:400]))

    def download(self, url: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        response = requests.get(url, timeout=600)
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
            "wan " + dest.name + " (" + str(seconds) + "s) " + self.model
            + " " + self.resolution + " mode=" + mode + extra,
            flush=True,
        )
        if dropped:
            refs = []
        self.clamp_duration(seconds, shot_id=dest.stem)
        self._normalize_resolution()
        self._normalize_model()
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
    media = (payload.get("input") or {}).get("media") or []
    types = [item.get("type") for item in media]
    prompt = str((payload.get("input") or {}).get("prompt") or "")
    params = payload.get("parameters") or {}
    return {
        "model": payload.get("model"),
        "duration": params.get("duration"),
        "resolution": params.get("resolution"),
        "ratio": params.get("ratio"),
        "audio": params.get("audio"),
        "prompt_extend": params.get("prompt_extend"),
        "watermark": params.get("watermark"),
        "media_types": types,
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
    parser = argparse.ArgumentParser(description="Alibaba Bailian Wan 3.0 I2V")
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

    backend = Wan3(require_key=not (args.check or args.dry_run))
    print(
        json.dumps(
            {
                "model": backend.model,
                "base": backend.base,
                "resolution": backend.resolution,
                "ratio": backend.ratio,
                "audio": backend.audio,
                "prompt_extend": backend.prompt_extend,
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
        dest = dest or (prod / "05-shots" / "smoke-wan" / (shot_id + ".mp4"))
    if image is None or not prompt or seconds is None:
        raise SystemExit("need --image/--prompt/--seconds, or --prod plus --shot")
    if not image.exists():
        raise SystemExit("missing first frame " + str(image))
    if last is not None and not last.exists():
        raise SystemExit("missing last frame " + str(last))
    dest = dest or Path("wan-smoke.mp4")
    payload = backend.build_payload(image, prompt, int(seconds), mode=mode, last_frame=last)
    summary = _summarize_payload(payload)
    summary["image"] = str(image)
    summary["last"] = str(last) if last else None
    summary["dest"] = str(dest)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    if args.dry_run:
        print("dry-run only; no Wan task submitted", flush=True)
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
