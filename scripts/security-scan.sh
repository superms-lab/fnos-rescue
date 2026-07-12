#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"
patterns=(
  'BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY'
  'github_pat_[A-Za-z0-9_]+'
  'ghp_[A-Za-z0-9]+'
  'AKIA[0-9A-Z]{16}'
  '192\.168\.[0-9]{1,3}\.[0-9]{1,3}'
  '/Users/[A-Za-z0-9._-]+'
  '(password|passwd|secret)[[:space:]]*[:=][[:space:]]*[^[:space:]]+'
)
failed=0
for pattern in "${patterns[@]}"; do
  if git grep -n -I -E "$pattern" -- . \
    ':(exclude)package-lock.json' \
    ':(exclude)src/fnos_rescue/web_dist/**' \
    ':(exclude)scripts/security-scan.sh'; then
    failed=1
  fi
done
if test "$failed" = 1; then
  echo "sensitive or private material detected" >&2
  exit 2
fi
echo "security scan passed"
