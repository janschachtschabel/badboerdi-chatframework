"""One-shot export of the cross-encoder reranker to ONNX.

Usage:
    python -m scripts.export_reranker_onnx
    python -m scripts.export_reranker_onnx --no-quantize   # only fp32
    python -m scripts.export_reranker_onnx --model cross-encoder/ms-marco-MiniLM-L-6-v2

Output:
    backend/models/<model-slug>/           fp32 ONNX + tokenizer + config
    backend/models/<model-slug>-int8/      dynamically quantized int8 ONNX

Runtime only needs `onnxruntime` + `transformers` (no torch). The
rerank pipeline in `rag_service.py` picks up the exported dir via
`RAG_RERANK_BACKEND=onnx` and the `RAG_RERANK_MODEL_DIR` env var.

This script itself DOES need torch (for the export), but that's a
one-time cost on the dev/build machine; production runtime stays lean.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

DEFAULT_MODEL = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
REPO_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = REPO_ROOT / "models"


def _slugify(model_id: str) -> str:
    """HF model id → filesystem-safe dirname."""
    return model_id.replace("/", "__")


def export_fp32(model_id: str, out_dir: Path) -> None:
    from optimum.onnxruntime import ORTModelForSequenceClassification
    from transformers import AutoTokenizer

    print(f"[export] loading + converting: {model_id}")
    t0 = time.perf_counter()
    model = ORTModelForSequenceClassification.from_pretrained(model_id, export=True)
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out_dir)
    tokenizer.save_pretrained(out_dir)
    dt = time.perf_counter() - t0
    size_mb = sum(p.stat().st_size for p in out_dir.rglob("*") if p.is_file()) / 1_048_576
    print(f"[export] fp32 saved: {out_dir}  ({size_mb:.1f} MB, {dt:.1f}s)")


def quantize_int8(fp32_dir: Path, int8_dir: Path) -> None:
    """Dynamic int8 quantization — no calibration dataset needed."""
    from optimum.onnxruntime import ORTQuantizer
    from optimum.onnxruntime.configuration import AutoQuantizationConfig

    print(f"[quantize] int8 dynamic quantization -> {int8_dir}")
    t0 = time.perf_counter()
    quantizer = ORTQuantizer.from_pretrained(fp32_dir)
    # avx2 is broadly compatible; avx512_vnni would be faster on modern
    # Intel CPUs but falls back anyway if unsupported.
    qconfig = AutoQuantizationConfig.avx2(is_static=False, per_channel=False)
    int8_dir.mkdir(parents=True, exist_ok=True)
    quantizer.quantize(save_dir=int8_dir, quantization_config=qconfig)
    # Copy tokenizer files so the int8 dir is self-contained for runtime
    for name in ("tokenizer.json", "tokenizer_config.json", "vocab.txt",
                 "sentencepiece.bpe.model", "special_tokens_map.json",
                 "config.json"):
        src = fp32_dir / name
        if src.exists():
            (int8_dir / name).write_bytes(src.read_bytes())
    dt = time.perf_counter() - t0
    size_mb = sum(p.stat().st_size for p in int8_dir.rglob("*") if p.is_file()) / 1_048_576
    print(f"[quantize] int8 saved: {int8_dir}  ({size_mb:.1f} MB, {dt:.1f}s)")


def smoke_test(onnx_dir: Path) -> None:
    """Load the exported model via pure onnxruntime and run one pair."""
    import numpy as np
    import onnxruntime as ort
    from transformers import AutoTokenizer

    print(f"[smoke]   loading from {onnx_dir}")
    tokenizer = AutoTokenizer.from_pretrained(onnx_dir)
    onnx_file = onnx_dir / "model.onnx"
    if not onnx_file.exists():
        # Quantized model uses a different filename
        candidates = list(onnx_dir.glob("model*.onnx"))
        if not candidates:
            raise FileNotFoundError(f"No model*.onnx in {onnx_dir}")
        onnx_file = candidates[0]
    session = ort.InferenceSession(str(onnx_file), providers=["CPUExecutionProvider"])

    query = "Was ist WissenLebtOnline?"
    passages = [
        "WissenLebtOnline ist eine Plattform für offene Bildungsmaterialien.",
        "Die Photosynthese wandelt Licht in Energie um.",
    ]
    enc = tokenizer([query] * len(passages), passages, padding=True,
                    truncation=True, max_length=512, return_tensors="np")
    feed = {
        "input_ids": enc["input_ids"].astype(np.int64),
        "attention_mask": enc["attention_mask"].astype(np.int64),
    }
    if "token_type_ids" in enc:
        feed["token_type_ids"] = enc["token_type_ids"].astype(np.int64)
    t0 = time.perf_counter()
    out = session.run(None, feed)
    dt = (time.perf_counter() - t0) * 1000
    scores = out[0].squeeze(-1)
    print(f"[smoke]   scores: {scores.tolist()}  (on-topic should be higher)  [{dt:.1f}ms]")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    help=f"HF model id (default: {DEFAULT_MODEL})")
    ap.add_argument("--no-quantize", action="store_true",
                    help="Skip int8 quantization")
    ap.add_argument("--force", action="store_true",
                    help="Re-export even if output dirs exist")
    args = ap.parse_args()

    slug = _slugify(args.model)
    fp32_dir = MODELS_DIR / slug
    int8_dir = MODELS_DIR / f"{slug}-int8"

    if fp32_dir.exists() and not args.force:
        print(f"[export] fp32 dir exists, skipping: {fp32_dir}  (use --force to rebuild)")
    else:
        export_fp32(args.model, fp32_dir)

    if not args.no_quantize:
        if int8_dir.exists() and not args.force:
            print(f"[quantize] int8 dir exists, skipping: {int8_dir}")
        else:
            quantize_int8(fp32_dir, int8_dir)

    print()
    print("=== Smoke test ===")
    smoke_test(fp32_dir)
    if not args.no_quantize and int8_dir.exists():
        smoke_test(int8_dir)

    print()
    print("Next: set in .env")
    print(f"  RAG_RERANK=on")
    print(f"  RAG_RERANK_BACKEND=onnx")
    print(f"  RAG_RERANK_MODEL_DIR={int8_dir if not args.no_quantize else fp32_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
