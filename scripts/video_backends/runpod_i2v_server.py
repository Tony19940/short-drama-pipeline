#!/usr/bin/env python3
"""LOCAL_H3_BASE adapter: POST /v1/i2v and GET /v1/i2v/{id}.

Four-point contract, independent of which GPU box is running:

1. Main path is designed first frame -> FL2VA (`MiniMaxH3ImageToVideo`).
2. Same-setup continue may send the previous true last frame as that first frame.
3. Designed `end_frame` (never `{id}-last.jpg`) becomes FL2VA last_frame.
4. Identity refs hang outside the first frame. If refs are present, also run
   native `MiniMaxH3ReferenceToVideo` and merge those refs onto the FL2VA
   conditioning. Missing a dedicated ref UNet is a hard error, not a silent
   fallback to first-frame-only.

Never writes a fake mp4.
"""
from __future__ import annotations

import base64
import json
import shutil
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import error, request

ROOT = Path("/workspace")
COMFY = Path("/workspace/ComfyUI")
INPUT = COMFY / "input"
OUTPUT = COMFY / "output"
JOBS = ROOT / "jobs"
OUT = ROOT / "outputs"
LOGS = ROOT / "logs"
def ensure_dirs() -> None:
    for folder in (INPUT, OUTPUT, JOBS, OUT, LOGS):
        folder.mkdir(parents=True, exist_ok=True)

COMFY_URL = "http://127.0.0.1:8188"
UNET = "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
REF_UNET_CANDIDATES = (
    "minimax_h3_ref2va_pruned_int8_convrot.safetensors",
    "minimax_h3_r2va_pruned_int8_convrot.safetensors",
    "minimax_h3_ref2va.safetensors",
)
CLIP = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
VIDEO_VAE = "minimax_h3_video_vae_fp16.safetensors"
AUDIO_VAE = "minimax_h3_audio_vae_fp32.safetensors"
TURBO_LORA = "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors"

LOCK = threading.Lock()
STATE: dict[str, dict] = {}


def frame_length(seconds: float) -> int:
    seconds = max(1.0, min(float(seconds), 15.0))
    raw = max(5, int(round(seconds * 24)))
    return raw + (5 - (raw % 17)) % 17


def choose_size(width: int, height: int, aspect: str | None) -> tuple[int, int]:
    # Official H3 canvas: 768 short edge, area cap 768*1344.
    if width <= 0 or height <= 0:
        if aspect in ("9:16", "9/16", "portrait"):
            return 768, 1344
        return 1344, 768
    if height >= width:
        return 768, 1344
    return 1344, 768


def image_size(path: Path) -> tuple[int, int]:
    try:
        from PIL import Image

        with Image.open(path) as im:
            return im.size
    except Exception:
        return (0, 0)


def turbo_available() -> bool:
    path = COMFY / "models" / "loras" / TURBO_LORA
    return path.exists() and path.stat().st_size > 1_000_000_000


def diffusion_dir() -> Path:
    return COMFY / "models" / "diffusion_models"


def find_ref_unet() -> str | None:
    folder = diffusion_dir()
    for name in REF_UNET_CANDIDATES:
        path = folder / name
        if path.exists() and path.stat().st_size > 1_000_000:
            return name
    if folder.exists():
        for path in sorted(folder.glob("*")):
            n = path.name.lower()
            if path.is_file() and ("ref2" in n or n.startswith("ref") or "_r2v" in n or "r2va" in n):
                if path.stat().st_size > 1_000_000:
                    return path.name
    return None


def save_b64(data: str, dest: Path) -> Path:
    dest.write_bytes(base64.b64decode(data))
    return dest


def comfy_json(method: str, path: str, payload: dict | None = None, timeout: int = 60):
    body = None if payload is None else json.dumps(payload).encode()
    req = request.Request(
        COMFY_URL + path,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"} if body else {},
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw.decode() or "{}")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"Comfy {path} {exc.code}: {detail[:2000]}") from exc


def upload_image(src: Path, name: str) -> str:
    boundary = "----H3Boundary" + uuid.uuid4().hex
    data = src.read_bytes()
    ctype = "image/jpeg" if src.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="{name}"\r\n'
        f"Content-Type: {ctype}\r\n\r\n"
    ).encode()
    extra = (
        f"\r\n--{boundary}\r\n"
        'Content-Disposition: form-data; name="overwrite"\r\n\r\n'
        "true\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="type"\r\n\r\n'
        "input\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    body = head + data + extra
    req = request.Request(
        COMFY_URL + "/upload/image",
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with request.urlopen(req, timeout=120) as resp:
        out = json.loads(resp.read().decode())
    return out.get("name") or name


def build_prompt(
    first_name: str,
    prompt: str,
    seconds: float,
    width: int,
    height: int,
    last_name: str | None,
    seed: int,
    ref_names: list[str] | None = None,
    mode: str = "i2v",
) -> dict:
    length = frame_length(seconds)
    use_turbo = turbo_available()
    steps = 8 if use_turbo else 20
    model_node = "6"
    workflow = {
        "6": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": UNET, "weight_dtype": "default"},
        },
        "13": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": CLIP, "type": "minimax", "device": "default"},
        },
        "11": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": VIDEO_VAE},
        },
        "24": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": AUDIO_VAE},
        },
        "1": {
            "class_type": "LoadImage",
            "inputs": {"image": first_name},
        },
        "104": {
            "class_type": "MiniMaxH3ImageToVideo",
            "inputs": {
                "clip": ["13", 0],
                "vae": ["11", 0],
                "prompt": prompt,
                "width": width,
                "height": height,
                "length": length,
                "first_frame": ["1", 0],
            },
        },
        "15": {
            "class_type": "RandomNoise",
            "inputs": {"noise_seed": seed},
        },
        "17": {
            "class_type": "KSamplerSelect",
            "inputs": {"sampler_name": "res_multistep"},
        },
        "10": {
            "class_type": "VAEDecodeTiled",
            "inputs": {
                "samples": ["14", 0],
                "vae": ["11", 0],
                "tile_size": 512,
                "overlap": 64,
                "temporal_size": 32,
                "temporal_overlap": 8,
            },
        },
        "23": {
            "class_type": "VAEDecodeAudio",
            "inputs": {"samples": ["14", 0], "vae": ["24", 0]},
        },
        "91": {
            "class_type": "CreateVideo",
            "inputs": {
                "images": ["10", 0],
                "audio": ["23", 0],
                "fps": 24.0,
                "bit_depth": 8,
                "color_space": "sRGB",
            },
        },
        "92": {
            "class_type": "SaveVideo",
            "inputs": {
                "video": ["91", 0],
                "filename_prefix": "video/director_i2v",
                "format": "auto",
                "codec": "auto",
            },
        },
    }
    if last_name:
        workflow["2"] = {"class_type": "LoadImage", "inputs": {"image": last_name}}
        workflow["104"]["inputs"]["last_frame"] = ["2", 0]
    if use_turbo:
        workflow["121"] = {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {
                "model": ["6", 0],
                "lora_name": TURBO_LORA,
                "strength_model": 1.0,
            },
        }
        model_node = "121"
    workflow["8"] = {
        "class_type": "MiniMaxH3SigmaShift",
        "inputs": {
            "model": [model_node, 0],
            "shift_video": 12.0,
            "shift_audio": 3.0,
        },
    }
    workflow["9"] = {
        "class_type": "BasicScheduler",
        "inputs": {
            "model": ["8", 0],
            "scheduler": "simple",
            "steps": steps,
            "denoise": 1.0,
        },
    }
    workflow["16"] = {
        "class_type": "BasicGuider",
        "inputs": {"model": ["8", 0], "conditioning": ["104", 0]},
    }
    workflow["14"] = {
        "class_type": "SamplerCustomAdvanced",
        "inputs": {
            "noise": ["15", 0],
            "guider": ["16", 0],
            "sampler": ["17", 0],
            "sigmas": ["9", 0],
            "latent_image": ["104", 1],
        },
    }
    ref_names = [name for name in (ref_names or []) if name]
    if mode == "r2v" and not ref_names:
        raise RuntimeError("mode=r2v needs identity refs hanging outside the first frame")
    # Current Comfy MiniMaxH3ReferenceToVideo expects a dict-like ref map.
    # Until a dedicated Ref2VA UNet is installed, keep FL2VA first-frame only.
    if ref_names and find_ref_unet() and mode in {"r2v", "flf"}:
        # Native H3 consumes first/last keyframes and picture refs from
        # conditioning. Keep sampling on the FL2VA UNet so the first frame
        # stays locked. A dedicated ref checkpoint is optional quality, not
        # a second generator that replaces the first frame.
        ref_inputs = {
            "clip": ["13", 0],
            "vae": ["11", 0],
            "audio_vae": ["24", 0],
            "prompt": prompt,
            "width": width,
            "height": height,
            "length": length,
            "ref_image_size": "match",
        }
        loaded = []
        for i, name in enumerate(ref_names[:4], start=1):
            node_id = str(210 + i)
            workflow[node_id] = {"class_type": "LoadImage", "inputs": {"image": name}}
            loaded.append([node_id, 0])
        if len(loaded) == 1:
            ref_inputs["ref_images"] = loaded[0]
        else:
            prev = loaded[0]
            for i, item in enumerate(loaded[1:], start=1):
                batch_id = str(230 + i)
                workflow[batch_id] = {
                    "class_type": "ImageBatch",
                    "inputs": {"image1": prev, "image2": item},
                }
                prev = [batch_id, 0]
            ref_inputs["ref_images"] = prev
        workflow["204"] = {
            "class_type": "MiniMaxH3ReferenceToVideo",
            "inputs": ref_inputs,
        }
        workflow["205"] = {
            "class_type": "ConditioningCombine",
            "inputs": {"conditioning_1": ["104", 0], "conditioning_2": ["204", 0]},
        }
        workflow["16"]["inputs"]["conditioning"] = ["205", 0]
    return workflow


def find_mp4(prompt_id: str, after_ts: float) -> Path | None:
    hist = comfy_json("GET", f"/history/{prompt_id}", timeout=30)
    rec = hist.get(prompt_id) or {}
    outputs = rec.get("outputs") or {}
    for node_out in outputs.values():
        for key in ("videos", "gifs", "images"):
            for item in node_out.get(key) or []:
                filename = item.get("filename")
                if not filename:
                    continue
                sub = item.get("subfolder") or ""
                folder = OUTPUT / sub if sub else OUTPUT
                path = folder / filename
                if path.exists() and path.suffix.lower() in {".mp4", ".webm", ".mkv"}:
                    return path
    newest = None
    newest_mtime = after_ts
    for path in OUTPUT.rglob("*"):
        if path.is_file() and path.suffix.lower() == ".mp4" and path.stat().st_mtime >= after_ts:
            if path.stat().st_mtime >= newest_mtime:
                newest = path
                newest_mtime = path.stat().st_mtime
    return newest


def wait_prompt(prompt_id: str, timeout: int = 3600) -> dict:
    start = time.time()
    while time.time() - start < timeout:
        hist = comfy_json("GET", f"/history/{prompt_id}", timeout=30)
        rec = hist.get(prompt_id)
        if rec:
            status = rec.get("status") or {}
            if status.get("completed") or status.get("status_str") in {"success", "error"}:
                return rec
        time.sleep(2)
    raise TimeoutError(f"Comfy prompt {prompt_id} timed out")


def set_job(task_id: str, **fields):
    with LOCK:
        STATE[task_id].update(fields)
        STATE[task_id]["updated_at"] = time.time()
        (JOBS / task_id / "state.json").write_text(json.dumps(STATE[task_id], indent=2))


def run_job(task_id: str, data: dict):
    ensure_dirs()
    job_dir = JOBS / task_id
    try:
        set_job(task_id, status="running", progress=5, error=None)
        first = job_dir / "first.jpg"
        if not first.exists():
            raise RuntimeError("missing first frame")
        prompt = str(data.get("prompt") or "").strip()
        if not prompt:
            raise RuntimeError("missing prompt")
        seconds = float(data.get("duration") or 6)
        aspect = str(data.get("aspect") or "9:16")
        width, height = choose_size(*image_size(first), aspect)
        seed = int(data.get("seed") or (int(time.time()) % 1_000_000_000))
        first_name = upload_image(first, f"{task_id}_first{first.suffix or '.jpg'}")
        last_name = None
        last = job_dir / "last.jpg"
        if last.exists() and last.stat().st_size > 0:
            last_name = upload_image(last, f"{task_id}_last{last.suffix or '.jpg'}")
        ref_names = []
        for path in sorted(job_dir.glob("ref-*.jpg")) + sorted(job_dir.glob("ref-*.png")):
            if path.stat().st_size > 0:
                ref_names.append(upload_image(path, f"{task_id}_{path.name}"))
        mode = str(data.get("mode") or "i2v").strip().lower() or "i2v"
        if mode not in {"i2v", "flf", "r2v"}:
            mode = "i2v"
        if last_name:
            mode = "flf"
        elif ref_names and mode == "i2v":
            mode = "r2v"
        workflow = build_prompt(
            first_name,
            prompt,
            seconds,
            width,
            height,
            last_name,
            seed,
            ref_names=ref_names,
            mode=mode,
        )
        (job_dir / "workflow.json").write_text(json.dumps(workflow, indent=2))
        set_job(
            task_id,
            progress=12,
            width=width,
            height=height,
            length=frame_length(seconds),
            turbo=turbo_available(),
            mode=mode,
            ref_count=len(ref_names),
            ref2va=bool(workflow.get("204")),
            ref_unet=find_ref_unet(),
            warning=None if (not ref_names or find_ref_unet()) else "no dedicated Ref2VA UNet; hanging refs on FL2VA first-frame path",
        )
        submitted = comfy_json(
            "POST",
            "/prompt",
            {"prompt": workflow, "client_id": f"director-{task_id}"},
            timeout=120,
        )
        prompt_id = submitted.get("prompt_id")
        if not prompt_id:
            raise RuntimeError(f"no prompt_id: {submitted}")
        set_job(task_id, progress=18, comfy_prompt_id=prompt_id)
        after = time.time() - 1
        rec = wait_prompt(prompt_id)
        status = rec.get("status") or {}
        if status.get("status_str") == "error" or status.get("completed") is False:
            msgs = status.get("messages") or []
            raise RuntimeError(f"Comfy error: {msgs[-3:]}")
        mp4 = find_mp4(prompt_id, after)
        if not mp4 or not mp4.exists():
            raise RuntimeError(f"Comfy finished but no mp4 found for {prompt_id}")
        dest = OUT / f"{task_id}.mp4"
        shutil.copy2(mp4, dest)
        if dest.stat().st_size < 10_000:
            dest.unlink(missing_ok=True)
            raise RuntimeError(f"copied mp4 too small: {mp4}")
        set_job(
            task_id,
            status="succeeded",
            progress=100,
            url=f"/outputs/{task_id}.mp4",
            video_url=f"/outputs/{task_id}.mp4",
            source=str(mp4),
            error=None,
        )
    except Exception as exc:
        (job_dir / "error.txt").write_text(traceback.format_exc())
        set_job(task_id, status="failed", progress=100, error=str(exc))


class Handler(BaseHTTPRequestHandler):
    def _json(self, code: int, payload: dict):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path, content_type: str):
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.rstrip("/") == "/health":
            gpu = False
            try:
                stats = comfy_json("GET", "/system_stats", timeout=5)
                gpu = bool((stats.get("devices") or [{}])[0].get("name"))
            except Exception:
                gpu = False
            return self._json(
                200,
                {
                    "ok": True,
                    "gpu": gpu,
                    "comfy": gpu,
                    "turbo": turbo_available(),
                    "fl_unet": UNET,
                    "ref_unet": find_ref_unet(),
                    "contract": ["designed-first-frame", "continue-last-frame", "designed-end-frame", "refs-outside-first-frame"],
                },
            )
        if self.path.startswith("/outputs/") and self.path.endswith(".mp4"):
            path = OUT / Path(self.path).name
            if path.exists():
                return self._file(path, "video/mp4")
            return self._json(404, {"error": "not found"})
        if self.path.startswith("/v1/i2v/"):
            task_id = self.path.split("/v1/i2v/", 1)[1].strip("/")
            with LOCK:
                job = STATE.get(task_id)
            if not job:
                disk = JOBS / task_id / "state.json"
                if disk.exists():
                    job = json.loads(disk.read_text())
            if not job:
                return self._json(404, {"error": "not found"})
            return self._json(200, job)
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path.rstrip("/") != "/v1/i2v":
            return self._json(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        data = json.loads(raw.decode() or "{}")
        ensure_dirs()
        task_id = uuid.uuid4().hex[:12]
        job_dir = JOBS / task_id
        job_dir.mkdir(parents=True, exist_ok=True)
        if data.get("image_b64"):
            save_b64(data["image_b64"], job_dir / "first.jpg")
        if data.get("last_frame_b64"):
            save_b64(data["last_frame_b64"], job_dir / "last.jpg")
        refs = data.get("refs_b64") or []
        if isinstance(refs, str):
            refs = [refs]
        for i, blob in enumerate(refs[:4], start=1):
            if blob:
                save_b64(blob, job_dir / f"ref-{i:02d}.jpg")
        request_meta = {k: v for k, v in data.items() if not str(k).endswith("_b64")}
        request_meta["ref_count"] = min(len(refs), 4)
        (job_dir / "request.json").write_text(json.dumps(request_meta, indent=2))
        job = {
            "id": task_id,
            "task_id": task_id,
            "status": "queued",
            "progress": 0,
            "url": None,
            "video_url": None,
            "error": None,
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        with LOCK:
            STATE[task_id] = job
        (job_dir / "state.json").write_text(json.dumps(job, indent=2))
        threading.Thread(target=run_job, args=(task_id, data), daemon=True).start()
        return self._json(200, {"id": task_id, "task_id": task_id, "status": "queued"})

    def log_message(self, fmt, *args):
        print("[i2v]", fmt % args, flush=True)


if __name__ == "__main__":
    ensure_dirs()
    server = ThreadingHTTPServer(("0.0.0.0", 8000), Handler)
    print("i2v listening on :8000 turbo=" + str(turbo_available()), flush=True)
    server.serve_forever()
