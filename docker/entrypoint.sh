#!/bin/sh
set -eu

PORT_VALUE="${PORT:-8080}"

# Default runtime identity (kept for compatibility with existing images).
DEFAULT_UID="${APP_UID:-10001}"
DEFAULT_GID="${APP_GID:-10001}"
TARGET_UID="$DEFAULT_UID"
TARGET_GID="$DEFAULT_GID"

# If /data is mounted, prefer running as its owner/group to avoid chmod 777.
if [ -d /data ]; then
  DATA_UID="$(stat -c '%u' /data 2>/dev/null || true)"
  DATA_GID="$(stat -c '%g' /data 2>/dev/null || true)"
  if [ -n "${DATA_UID}" ] && [ -n "${DATA_GID}" ]; then
    TARGET_UID="${DATA_UID}"
    TARGET_GID="${DATA_GID}"
  fi
fi

if [ "$(id -u)" -eq 0 ]; then
  # If mounted volume is root-owned, keep root to preserve writability.
  if [ "${TARGET_UID}" = "0" ] || [ "${TARGET_GID}" = "0" ]; then
    exec uvicorn backend.main:app --host 0.0.0.0 --port "${PORT_VALUE}"
  fi
  exec gosu "${TARGET_UID}:${TARGET_GID}" uvicorn backend.main:app --host 0.0.0.0 --port "${PORT_VALUE}"
fi

exec uvicorn backend.main:app --host 0.0.0.0 --port "${PORT_VALUE}"
