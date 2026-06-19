#!/usr/bin/env bash
# Fast local quality gate for Hermes Agent development.
#
# Usage:
#   scripts/code_health.sh                 # quick checks on changed Python files + focused tests
#   scripts/code_health.sh --full          # full Python lint/type/compile/test suite
#   scripts/code_health.sh --base main     # compare changed files against another ref
#   scripts/code_health.sh --tests tests/gateway/test_foo.py -- --tb=long
#
# Everything after '--' is passed through to pytest when tests are run.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

MODE="quick"
BASE=""
STRICT_TY=0
TEST_TARGETS=()
PYTEST_ARGS=()

usage() {
  cat <<'USAGE'
Fast local quality gate for Hermes Agent development.

Usage:
  scripts/code_health.sh                 # quick checks on changed Python files + focused tests
  scripts/code_health.sh --full          # full Python lint/compile/test suite; ty remains advisory
  scripts/code_health.sh --strict-ty     # make ty diagnostics fail the script
  scripts/code_health.sh --base main     # compare changed files against another ref
  scripts/code_health.sh --tests tests/gateway/test_foo.py -- --tb=long

Everything after '--' is passed through to pytest when tests are run.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --full)
      MODE="full"
      shift
      ;;
    --quick)
      MODE="quick"
      shift
      ;;
    --strict-ty)
      STRICT_TY=1
      shift
      ;;
    --base)
      BASE="${2:-}"
      if [[ -z "$BASE" ]]; then
        echo "error: --base requires a git ref" >&2
        exit 2
      fi
      shift 2
      ;;
    --tests)
      shift
      while [[ $# -gt 0 && "$1" != "--" ]]; do
        TEST_TARGETS+=("$1")
        shift
      done
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    --)
      shift
      PYTEST_ARGS+=("$@")
      break
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

cd "$REPO_ROOT"

VENV=""
for candidate in "$REPO_ROOT/.venv" "$REPO_ROOT/venv" "$HOME/.hermes/hermes-agent/venv"; do
  if [[ -x "$candidate/bin/python" ]]; then
    VENV="$candidate"
    break
  fi
done

if [[ -z "$VENV" ]]; then
  echo "error: no Python virtualenv found (.venv, venv, or ~/.hermes/hermes-agent/venv)" >&2
  exit 1
fi

PYTHON="$VENV/bin/python"
export TZ=UTC
export LANG=C.UTF-8
export LC_ALL=C.UTF-8
export PYTHONHASHSEED=0

run() {
  echo
  echo "▶ $*"
  "$@"
}

have_module() {
  "$PYTHON" - "$1" <<'PY'
import importlib.util
import sys
sys.exit(0 if importlib.util.find_spec(sys.argv[1]) else 1)
PY
}

run_ty() {
  if ! have_module ty; then
    echo "⚠ skipping ty: module not installed in $VENV" >&2
    return 0
  fi

  if [[ "$STRICT_TY" == "1" ]]; then
    run "$PYTHON" -m ty check --python "$PYTHON" --no-progress "$@"
  else
    echo
    echo "▶ $PYTHON -m ty check --python $PYTHON --no-progress --exit-zero $*"
    "$PYTHON" -m ty check --python "$PYTHON" --no-progress --exit-zero "$@" | sed -n '1,160p'
    echo "ℹ ty diagnostics are advisory by default because this codebase has an existing type baseline. Use --strict-ty to fail on them."
  fi
}

if [[ -z "$BASE" ]]; then
  if git rev-parse --verify origin/main >/dev/null 2>&1; then
    BASE="origin/main"
  else
    BASE="HEAD~1"
  fi
fi

mapfile -t CHANGED_PY < <(
  {
    git diff --name-only --diff-filter=ACMR "$BASE"...HEAD -- '*.py' 2>/dev/null || true
    git diff --name-only --diff-filter=ACMR -- '*.py' 2>/dev/null || true
    git ls-files --others --exclude-standard -- '*.py' 2>/dev/null || true
  } | sort -u
)

if [[ "$MODE" == "full" ]]; then
  echo "Hermes code health: full suite"
  echo "Python: $($PYTHON -V)"

  if have_module ruff; then
    run "$PYTHON" -m ruff check .
  else
    echo "⚠ skipping ruff: module not installed in $VENV" >&2
  fi

  run_ty .

  run "$PYTHON" -m compileall -q \
    run_agent.py model_tools.py toolsets.py batch_runner.py cli.py hermes_bootstrap.py \
    hermes_constants.py hermes_state.py hermes_time.py hermes_logging.py utils.py \
    agent tools hermes_cli gateway cron acp_adapter providers tui_gateway plugins

  if [[ -x "$SCRIPT_DIR/check-windows-footguns.py" ]]; then
    run "$PYTHON" "$SCRIPT_DIR/check-windows-footguns.py" --all
  fi

  if [[ ${#TEST_TARGETS[@]} -eq 0 ]]; then
    run "$SCRIPT_DIR/run_tests.sh" -- "${PYTEST_ARGS[@]}"
  else
    run "$SCRIPT_DIR/run_tests.sh" "${TEST_TARGETS[@]}" -- "${PYTEST_ARGS[@]}"
  fi
else
  echo "Hermes code health: quick changed-file gate"
  echo "Base ref: $BASE"
  echo "Python: $($PYTHON -V)"

  if [[ ${#CHANGED_PY[@]} -eq 0 ]]; then
    echo "No changed Python files detected against $BASE."
  else
    printf 'Changed Python files:\n'
    printf '  %s\n' "${CHANGED_PY[@]}"

    if have_module ruff; then
      run "$PYTHON" -m ruff check "${CHANGED_PY[@]}"
    else
      echo "⚠ skipping ruff: module not installed in $VENV" >&2
    fi

    run_ty "${CHANGED_PY[@]}"

    run "$PYTHON" -m py_compile "${CHANGED_PY[@]}"

    if [[ -x "$SCRIPT_DIR/check-windows-footguns.py" ]]; then
      run "$PYTHON" "$SCRIPT_DIR/check-windows-footguns.py" "${CHANGED_PY[@]}"
    fi
  fi

  if [[ ${#TEST_TARGETS[@]} -gt 0 ]]; then
    run "$SCRIPT_DIR/run_tests.sh" "${TEST_TARGETS[@]}" -- "${PYTEST_ARGS[@]}"
  else
    mapfile -t CHANGED_TESTS < <(printf '%s\n' "${CHANGED_PY[@]}" | awk '/^tests\/.*test_.*\.py$/')
    if [[ ${#CHANGED_TESTS[@]} -gt 0 ]]; then
      run "$SCRIPT_DIR/run_tests.sh" "${CHANGED_TESTS[@]}" -- "${PYTEST_ARGS[@]}"
    else
      echo "No changed test files detected. Pass --tests <path> to run focused tests."
    fi
  fi
fi

echo
echo "✅ Hermes code health checks passed."
