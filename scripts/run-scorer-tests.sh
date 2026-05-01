#!/usr/bin/env bash
set -Eeuo pipefail

current_step=""

trap 'status=$?; if [[ $status -ne 0 && -n "${current_step:-}" ]]; then echo "[scorer:test] FAIL ${current_step}" >&2; fi' ERR

run_step() {
  current_step="$1"
  shift
  echo "[scorer:test] START ${current_step}"
  "$@"
  echo "[scorer:test] PASS ${current_step}"
  current_step=""
}

run_step "Official compiled runtime regression fixture" \
  python3 agora-scorer-compiled/test_score.py

run_step "Runtime manifest split fixture" \
  python3 common/test_runtime_manifest.py
