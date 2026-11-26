#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1
# Dependency installation is explicit; no network is used by audit/replay/test.
if [ "${1:-}" = '--install' ]; then
  python3.12 -m venv .venv
  timeout 600 .venv/bin/python -m pip install -r requirements.lock
fi
if [ -x .venv/bin/python ]; then
  python_exec=.venv/bin/python
else
  python_exec=python3
  if [ -d .deps ]; then export PYTHONPATH="$PWD/.deps${PYTHONPATH:+:$PYTHONPATH}"; fi
fi
timeout 600 "$python_exec" -B tests.py
timeout 600 "$python_exec" -B replay.py
