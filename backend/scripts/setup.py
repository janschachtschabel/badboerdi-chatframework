"""One-shot setup after a fresh `git clone`.

Ensures that build artifacts which are NOT committed to git are present
before the backend starts. Currently that's just the RAG reranker
(ONNX int8 export of cross-encoder/mmarco-mMiniLMv2-L12-H384-v1).

Usage:
    cd backend
    pip install -r requirements-setup.txt \
        --extra-index-url https://download.pytorch.org/whl/cpu
    python -m scripts.setup

Idempotent: re-running is safe; already-exported artifacts are detected
and skipped. Backend works without running this — reranker silently
falls back to embedding-only ranking if the model dir is missing.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent  # backend/
RERANKER_INT8_DIR = (
    REPO_ROOT / "models"
    / "cross-encoder__mmarco-mMiniLMv2-L12-H384-v1-int8"
)


def _has_reranker() -> bool:
    return RERANKER_INT8_DIR.exists() and any(RERANKER_INT8_DIR.glob("*.onnx"))


def _export_reranker() -> int:
    print("[setup] exporting RAG reranker to ONNX (one-time, ~1 min)...")
    cmd = [sys.executable, "-m", "scripts.export_reranker_onnx"]
    try:
        proc = subprocess.run(cmd, cwd=str(REPO_ROOT))
        return proc.returncode
    except FileNotFoundError as e:
        print(f"[setup] ERROR: {e}")
        return 1


def _check_export_deps() -> bool:
    """Verify the setup-only dependencies are installed."""
    missing = []
    for mod in ("optimum", "sentence_transformers", "torch"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        print("[setup] ERROR: missing setup dependencies: " + ", ".join(missing))
        print("[setup] Install with:")
        print("        pip install -r requirements-setup.txt \\")
        print("          --extra-index-url https://download.pytorch.org/whl/cpu")
        return False
    return True


def main() -> int:
    print("=== BadBoerdi backend setup ===")

    if _has_reranker():
        print(f"[setup] reranker OK: {RERANKER_INT8_DIR}")
        return 0

    if not _check_export_deps():
        return 1

    rc = _export_reranker()
    if rc != 0:
        print(f"[setup] reranker export failed (rc={rc})")
        return rc

    if not _has_reranker():
        print("[setup] reranker export completed but model dir is still missing?")
        return 1

    print("[setup] all build artifacts present")
    print()
    print("Next: python run.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
