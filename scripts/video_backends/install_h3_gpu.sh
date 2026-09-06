#!/usr/bin/env bash
# Install ComfyUI + MiniMax H3 FL2VA on a fresh GPU box.
# Does NOT download Ref2VA. Inspect and print REF2VA_MISSING instead.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
export HF_HUB_ENABLE_HF_TRANSFER=1
ROOT=/workspace
COMFY="$ROOT/ComfyUI"
LOG="$ROOT/logs/install_h3.log"
mkdir -p "$ROOT/logs" "$ROOT/jobs" "$ROOT/outputs"

exec > >(tee -a "$LOG") 2>&1
echo "=== H3 install $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

if [[ ! -d "$COMFY/.git" ]]; then
  git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git "$COMFY"
fi
cd "$COMFY"
python3 -m pip install -U pip wheel
python3 -m pip install -r requirements.txt
python3 -m pip install -U huggingface_hub hf_transfer pillow

mkdir -p "$COMFY/models/diffusion_models" "$COMFY/models/text_encoders" "$COMFY/models/vae" "$COMFY/models/loras" "$COMFY/models/embeddings"

download() {
  local repo="$1" file="$2" dest="$3"
  if [[ -f "$dest" ]]; then
    local size
    size="$(stat -c%s "$dest" 2>/dev/null || echo 0)"
    if [[ "$size" -gt 1000000 ]]; then
      echo "exists $dest ($size)"
      return
    fi
  fi
  echo "download $repo $file -> $dest"
  python3 - "$repo" "$file" "$dest" <<'PY2'
import os, shutil, sys
from huggingface_hub import hf_hub_download
repo, file, dest = sys.argv[1], sys.argv[2], sys.argv[3]
path = hf_hub_download(repo_id=repo, filename=file)
os.makedirs(os.path.dirname(dest), exist_ok=True)
if os.path.abspath(path) != os.path.abspath(dest):
    shutil.copy2(path, dest)
print("ok", dest, os.path.getsize(dest))
PY2
}

REPO=Comfy-Org/MiniMax-H3
download "$REPO" diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors "$COMFY/models/diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors"
download "$REPO" text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors "$COMFY/models/text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
download "$REPO" vae/minimax_h3_video_vae_fp16.safetensors "$COMFY/models/vae/minimax_h3_video_vae_fp16.safetensors"
download "$REPO" vae/minimax_h3_audio_vae_fp32.safetensors "$COMFY/models/vae/minimax_h3_audio_vae_fp32.safetensors"
download "$REPO" loras/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors "$COMFY/models/loras/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors"

echo "=== WEIGHTS ==="
ls -lh "$COMFY/models/diffusion_models" || true
ls -lh "$COMFY/models/text_encoders" || true
ls -lh "$COMFY/models/vae" || true
ls -lh "$COMFY/models/loras" || true
python3 - <<'PY3'
from pathlib import Path
folder = Path("/workspace/ComfyUI/models/diffusion_models")
hits = []
if folder.exists():
    for path in folder.iterdir():
        n = path.name.lower()
        if path.is_file() and ("ref2" in n or n.startswith("ref") or "_r2v" in n or "r2va" in n):
            hits.append(path.name)
print("REF2VA_FOUND" if hits else "REF2VA_MISSING")
for name in hits:
    print(name)
PY3
echo "=== INSTALL DONE ==="
