#!/usr/bin/env bash
# =============================================================================
# vLLM serving scripts for litmus evals
#
# Two deployment modes:
#   1. Single model, data-parallel 8 (all 8 GPUs)
#   2. Two models side-by-side, data-parallel 4 each (4 GPUs per model)
#
# inspect_ai discovers vllm models via the VLLM_BASE_URL env var
# and the "vllm/" model prefix in litmus eval --models.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHAT_TEMPLATE="${SCRIPT_DIR}/olmo_base_chat.jinja"

BASE_MODEL="allenai/OLMo-3-1025-7B"
SFT_MODEL="allenai/OLMo-3-7B-Think-SFT"

# -----------------------------------------------------------------------------
# Option 1: Single model on all 8 GPUs (data-parallel 8)
#
# Usage:
#   bash mats/serve.sh single
#
# Then run evals with:
#   export VLLM_BASE_URL=http://localhost:8000/v1
#   litmus eval --models vllm/allenai/OLMo-3-1025-7B --all
# -----------------------------------------------------------------------------
serve_single() {
    local model="${1:-$BASE_MODEL}"
    local port="${2:-8000}"

    echo "Serving ${model} on port ${port} with DP=8 (all GPUs)"

    CUDA_VISIBLE_DEVICES=0,1,2,3,4,5,6,7 \
    python -m vllm.entrypoints.openai.api_server \
        --model "${model}" \
        --chat-template "${CHAT_TEMPLATE}" \
        --tensor-parallel-size 1 \
        --data-parallel-size 8 \
        --port "${port}" \
        --max-model-len 4096
}

# -----------------------------------------------------------------------------
# Option 2: Two models side-by-side, 4 GPUs each
#
# Usage:
#   bash mats/serve.sh dual
#
# This launches:
#   - Base model on port 8000 (GPUs 0-3)
#   - SFT model  on port 8001 (GPUs 4-7)
#
# Then run evals with:
#   # Base model
#   export VLLM_BASE_URL=http://localhost:8000/v1
#   litmus eval --models vllm/allenai/OLMo-3-1025-7B --all
#
#   # SFT model
#   export VLLM_BASE_URL=http://localhost:8001/v1
#   litmus eval --models vllm/allenai/OLMo-3-7B-Think-SFT --all
#
#   # Or run both sequentially (switching base URL between runs):
#   VLLM_BASE_URL=http://localhost:8000/v1 \
#     litmus eval --models vllm/allenai/OLMo-3-1025-7B --all
#   VLLM_BASE_URL=http://localhost:8001/v1 \
#     litmus eval --models vllm/allenai/OLMo-3-7B-Think-SFT --all
# -----------------------------------------------------------------------------
serve_dual() {
    echo "Serving ${BASE_MODEL} on port 8000 (GPUs 0-3, DP=4)"
    echo "Serving ${SFT_MODEL} on port 8001 (GPUs 4-7, DP=4)"

    # Base model on GPUs 0-3
    CUDA_VISIBLE_DEVICES=0,1,2,3 \
    python -m vllm.entrypoints.openai.api_server \
        --model "${BASE_MODEL}" \
        --chat-template "${CHAT_TEMPLATE}" \
        --tensor-parallel-size 1 \
        --data-parallel-size 4 \
        --port 8000 \
        --max-model-len 4096 &

    # SFT model on GPUs 4-7
    CUDA_VISIBLE_DEVICES=4,5,6,7 \
    python -m vllm.entrypoints.openai.api_server \
        --model "${SFT_MODEL}" \
        --chat-template "${CHAT_TEMPLATE}" \
        --tensor-parallel-size 1 \
        --data-parallel-size 4 \
        --port 8001 \
        --max-model-len 4096 &

    echo ""
    echo "Both servers launching in background. Wait for 'Uvicorn running' messages."
    echo ""
    echo "To eval both models:"
    echo "  VLLM_BASE_URL=http://localhost:8000/v1 litmus eval --models vllm/allenai/OLMo-3-1025-7B --all"
    echo "  VLLM_BASE_URL=http://localhost:8001/v1 litmus eval --models vllm/allenai/OLMo-3-7B-Think-SFT --all"

    wait
}

# -----------------------------------------------------------------------------
# Entrypoint
# -----------------------------------------------------------------------------
case "${1:-}" in
    single)
        serve_single "${2:-}" "${3:-}"
        ;;
    dual)
        serve_dual
        ;;
    *)
        echo "Usage: bash mats/serve.sh <single|dual> [model] [port]"
        echo ""
        echo "  single [model] [port]  - One model on 8 GPUs (default: ${BASE_MODEL}, port 8000)"
        echo "  dual                   - Base on port 8000 (GPUs 0-3), SFT on port 8001 (GPUs 4-7)"
        exit 1
        ;;
esac
