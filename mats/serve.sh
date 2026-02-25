#!/usr/bin/env bash
# =============================================================================
# vLLM serving scripts for litmus evals
#
# Auto-detects GPU count and scales accordingly.
#
# inspect_ai discovers vllm models via the VLLM_BASE_URL env var
# and the "vllm/" model prefix in litmus eval --models.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHAT_TEMPLATE="${SCRIPT_DIR}/olmo_base_chat.jinja"

BASE_MODEL="allenai/OLMo-3-1025-7B"
SFT_MODEL="allenai/OLMo-3-7B-Think-SFT"

NUM_GPUS=$(nvidia-smi --query-gpu=index --format=csv,noheader | wc -l)
echo "Detected ${NUM_GPUS} GPU(s)"

# -----------------------------------------------------------------------------
# Option 1: Single model
#
# Usage:
#   bash mats/serve.sh single [model] [port]
#
# Then:
#   export VLLM_BASE_URL=http://localhost:8000/v1
#   litmus eval --models vllm/allenai/OLMo-3-1025-7B --all
#   VLLM_BASE_URL=http://localhost:8000/v1 litmus eval --models vllm/allenai/OLMo-3-1025-7B --behavior verbosity 
#   
# -----------------------------------------------------------------------------
serve_single() {
    local model="${1:-$SFT_MODEL}"
    local port="${2:-8000}"

    echo "Serving ${model} on port ${port} (DP=${NUM_GPUS})"

    python -m vllm.entrypoints.openai.api_server \
        --model "${model}" \
        --chat-template "${CHAT_TEMPLATE}" \
        --tensor-parallel-size 1 \
        --data-parallel-size "${NUM_GPUS}" \
        --port "${port}" \
        --max-model-len 4096 \
        --enforce-eager  # TODO: remove once flash-attn is rebuilt for torch 2.9.1+cu128
}

# -----------------------------------------------------------------------------
# Option 2: Two models side-by-side (requires >= 2 GPUs)
#
# Splits GPUs evenly: first half for base, second half for SFT.
#
# Usage:
#   bash mats/serve.sh dual
#
# Then:
#   VLLM_BASE_URL=http://localhost:8000/v1 litmus eval --models vllm/allenai/OLMo-3-1025-7B --all
#   VLLM_BASE_URL=http://localhost:8001/v1 litmus eval --models vllm/allenai/OLMo-3-7B-Think-SFT --all

#   VLLM_BASE_URL=http://localhost:8000/v1 litmus eval --models vllm/allenai/OLMo-3-1025-7B --hypotheses --claims
#   VLLM_BASE_URL=http://localhost:8001/v1 litmus eval --models vllm/allenai/OLMo-3-7B-Think-SFT --hypotheses --claims

# -----------------------------------------------------------------------------
serve_dual() {
    if [ "${NUM_GPUS}" -lt 2 ]; then
        echo "Error: dual mode requires >= 2 GPUs, found ${NUM_GPUS}"
        echo "Use 'bash mats/serve.sh single' and run models sequentially instead."
        exit 1
    fi

    local half=$((NUM_GPUS / 2))
    local first_gpus=$(seq -s, 0 $((half - 1)))
    local second_gpus=$(seq -s, "${half}" $((NUM_GPUS - 1)))

    echo "Serving ${BASE_MODEL} on port 8000 (GPUs ${first_gpus}, DP=${half})"
    echo "Serving ${SFT_MODEL} on port 8001 (GPUs ${second_gpus}, DP=${half})"

    CUDA_VISIBLE_DEVICES="${first_gpus}" \
    python -m vllm.entrypoints.openai.api_server \
        --model "${BASE_MODEL}" \
        --chat-template "${CHAT_TEMPLATE}" \
        --tensor-parallel-size 1 \
        --data-parallel-size "${half}" \
        --port 8000 \
        --max-model-len 4096 \
        --enforce-eager &

    CUDA_VISIBLE_DEVICES="${second_gpus}" \
    python -m vllm.entrypoints.openai.api_server \
        --model "${SFT_MODEL}" \
        --chat-template "${CHAT_TEMPLATE}" \
        --tensor-parallel-size 1 \
        --data-parallel-size "${half}" \
        --port 8001 \
        --max-model-len 4096 \
        --enforce-eager &

    echo ""
    echo "Both servers launching. Wait for 'Uvicorn running' messages."
    echo ""
    echo "To eval both models:"
    echo "  VLLM_BASE_URL=http://localhost:8000/v1 litmus eval --models vllm/${BASE_MODEL} --all"
    echo "  VLLM_BASE_URL=http://localhost:8001/v1 litmus eval --models vllm/${SFT_MODEL} --all"

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
        echo "  single [model] [port]  - One model on all ${NUM_GPUS} GPU(s)"
        echo "  dual                   - Base on :8000, SFT on :8001 (split GPUs)"
        exit 1
        ;;
esac
