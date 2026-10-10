#!/usr/bin/env bash
# Install the dependencies pinned by poetry.lock into a new virtualenv, with CPU-only torch.
#   scripts/install-python-deps.sh <venv_dir> [--with-dev]
# Used by docker/python.Dockerfile (main dependencies) and CI (with the dev group), so both
# install the same way. Needs `poetry` with `poetry-plugin-export`, run from the repository
# root. torch comes from PyTorch's CPU index: the PyPI wheel for linux/amd64 pulls several GB
# of CUDA libraries that are never used here, so the lock's CUDA-only packages (nvidia-*,
# cuda-*, triton) are left out as well.
set -euo pipefail

venv="${1:?usage: scripts/install-python-deps.sh <venv_dir> [--with-dev]}"
groups=(--only main)
if [[ "${2:-}" == "--with-dev" ]]; then
  groups=(--with dev)
fi

python -m venv "$venv"
requirements="${venv}/requirements.txt"
poetry export "${groups[@]}" --without-hashes -f requirements.txt -o "$requirements"
grep -v -E '^(torch|triton|nvidia-[a-z0-9-]+|cuda-[a-z0-9-]+)==' "$requirements" \
  >"${venv}/requirements-no-torch.txt"
torch="$(grep -E '^torch==' "$requirements" | cut -d';' -f1 | tr -d ' ')"
[[ -n "$torch" ]] || { echo "torch is not in poetry.lock" >&2; exit 1; }

"${venv}/bin/pip" install --index-url https://download.pytorch.org/whl/cpu "$torch"
"${venv}/bin/pip" install -r "${venv}/requirements-no-torch.txt"
"${venv}/bin/pip" check
if "${venv}/bin/pip" list --format=freeze | grep -i -E '^(nvidia-|cuda-|triton=)'; then
  echo "CUDA packages were installed; the CPU-only install failed" >&2
  exit 1
fi
