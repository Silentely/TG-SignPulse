#!/bin/sh
set -eu

PORT_VALUE="${PORT:-8080}"
AUTO_FIX_PERMS="${APP_AUTO_FIX_DATA_PERMS:-1}"

# 根据 LOG_LEVEL 控制 uvicorn access log
# DEBUG 时输出到 stderr，否则禁用（输出到 /dev/null）
LOG_LEVEL_UPPER="$(echo "${LOG_LEVEL:-INFO}" | tr '[:lower:]' '[:upper:]')"
if [ "${LOG_LEVEL_UPPER}" = "DEBUG" ]; then
  ACCESS_LOG_OPT="--access-log"
else
  ACCESS_LOG_OPT="--no-access-log"
fi

DEFAULT_UID="${APP_UID:-10001}"
DEFAULT_GID="${APP_GID:-10001}"

# 非 root 启动（Dockerfile 已 USER app）：直接以当前身份运行。
if [ "$(id -u)" -ne 0 ]; then
  if [ ! -d /data ] || [ ! -w /data ]; then
    echo "ERROR: 当前用户无法写入 /data；请修正挂载卷属主（chown -R 10001:10001 ./data）。" >&2
    exit 1
  fi
  exec uvicorn backend.main:app --host 0.0.0.0 --port "${PORT_VALUE}" ${ACCESS_LOG_OPT}
fi

# 以 root 启动时只做「把 /data 归属收敛到目标身份」这一件事，然后立即降权。
# fail-closed：chown 失败（只读挂载 / 不允许的属主）直接报错并非零退出，
# 不再回退到「保持 root 运行」——那会让容器长期以 root 持有会话与凭据文件。
if [ ! -d /data ]; then
  echo "ERROR: /data 不存在，无法确认数据目录归属；请挂载数据卷后重试。" >&2
  exit 1
fi

if [ "${AUTO_FIX_PERMS}" != "0" ]; then
  echo "INFO: fixing /data permissions for ${DEFAULT_UID}:${DEFAULT_GID} ..."
  mkdir -p /data/.signer /data/sessions /data/logs /data/plugins || true

  if ! chown -R "${DEFAULT_UID}:${DEFAULT_GID}" /data 2>/dev/null; then
    echo "ERROR: 无法把 /data 归属改为 ${DEFAULT_UID}:${DEFAULT_GID}；" >&2
    echo "       请修正挂载卷属主（chown -R ${DEFAULT_UID}:${DEFAULT_GID} ./data）" >&2
    echo "       或以 user: \"${DEFAULT_UID}:${DEFAULT_GID}\" 显式指定运行身份。" >&2
    exit 1
  fi

  for p in /data /data/.signer /data/sessions /data/logs /data/plugins; do
    if [ -e "${p}" ]; then
      chmod -R u+rwX "${p}" 2>/dev/null || true
    fi
  done
fi

exec gosu "${DEFAULT_UID}:${DEFAULT_GID}" \
  uvicorn backend.main:app --host 0.0.0.0 --port "${PORT_VALUE}" ${ACCESS_LOG_OPT}
