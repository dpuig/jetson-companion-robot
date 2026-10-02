#!/usr/bin/env bash
# Build the inference servers and fetch models (runs ON the Jetson, no sudo). Safe to re-run.
#   ~/opt/llama.cpp   llama-server   (Qwen3-VL-4B: text + images, OpenAI-compatible API)
#   ~/opt/whisper.cpp whisper-server (speech-to-text)
#   ~/models/         GGUF / ggml weights
# From the Mac: scripts/jetson.sh ai-setup
set -euo pipefail
export PATH=/usr/local/cuda/bin:$PATH

OPT=~/opt; MODELS=~/models; JOBS="${BUILD_JOBS:-4}"   # >4 parallel nvcc jobs risks OOM on 8 GB
mkdir -p "$OPT" "$MODELS"

build() {  # build <repo-url> <dir> <cmake-flags> <targets...>
  local url=$1 dir=$OPT/$2 flags=$3; shift 3
  [[ -d $dir ]] || git clone --depth 1 "$url" "$dir"
  git -C "$dir" pull --ff-only
  cmake -S "$dir" -B "$dir/build" -DCMAKE_BUILD_TYPE=Release -DCMAKE_CUDA_ARCHITECTURES=87 $flags
  cmake --build "$dir/build" -j"$JOBS" --target "$@"
}

fetch() {  # fetch <url> <file>: skip if already complete
  [[ -s $MODELS/$2 ]] && { echo "have $2"; return; }
  curl -fL --retry 3 -o "$MODELS/$2.part" "$1" && mv "$MODELS/$2.part" "$MODELS/$2"
}

echo ">> models"
HF=https://huggingface.co
fetch "$HF/Qwen/Qwen3-VL-4B-Instruct-GGUF/resolve/main/Qwen3VL-4B-Instruct-Q4_K_M.gguf"      Qwen3VL-4B-Instruct-Q4_K_M.gguf
fetch "$HF/Qwen/Qwen3-VL-4B-Instruct-GGUF/resolve/main/mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf"  mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf
fetch "$HF/ggerganov/whisper.cpp/resolve/main/ggml-small-q5_1.bin"                          ggml-small-q5_1.bin
fetch "$HF/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx"      en_US-lessac-medium.onnx
fetch "$HF/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json" en_US-lessac-medium.onnx.json

echo ">> llama.cpp"
build https://github.com/ggml-org/llama.cpp llama.cpp "-DGGML_CUDA=ON -DLLAMA_CURL=OFF" llama-server llama-mtmd-cli

echo ">> whisper.cpp"
build https://github.com/ggml-org/whisper.cpp whisper.cpp "-DGGML_CUDA=ON" whisper-server

echo ">> python deps (user site)"
python3 -m pip install --user --upgrade "numpy<2" piper-tts pypdf sounddevice webrtcvad-wheels fastapi uvicorn python-multipart requests

echo ">> done"; ls -lh "$MODELS"
