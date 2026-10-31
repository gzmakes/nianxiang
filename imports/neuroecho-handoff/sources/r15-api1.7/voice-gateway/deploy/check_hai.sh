#!/usr/bin/env bash
set -euo pipefail

# Read-only HAI preflight. Run this after SSH/Jupyter access is available;
# it intentionally does not install packages, open ports, or alter services.
printf 'user: '; whoami
printf 'host: '; hostname
uname -a
command -v nvidia-smi >/dev/null && nvidia-smi || echo 'nvidia-smi unavailable'
df -h
free -h || true
python --version
python - <<'PY'
try:
    import torch
except Exception as exc:
    print(f'torch import failed: {exc}')
else:
    print(f'torch={torch.__version__} cuda_available={torch.cuda.is_available()} cuda={torch.version.cuda}')
    if torch.cuda.is_available():
        for i in range(torch.cuda.device_count()):
            print(f'gpu[{i}]={torch.cuda.get_device_name(i)}')
PY

for port in 9880 9881; do
    if command -v ss >/dev/null; then ss -ltn "sport = :$port" || true; fi
done
