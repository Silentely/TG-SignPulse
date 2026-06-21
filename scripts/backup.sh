#!/usr/bin/env bash
set -euo pipefail

# 解析脚本所在目录的绝对路径，确保从任意工作目录执行都能正确定位
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DATA_DIR="${APP_DATA_DIR:-$PROJECT_ROOT/data}"

# 验证 data 目录存在
if [ ! -d "$DATA_DIR" ]; then
    echo "错误: 数据目录不存在: $DATA_DIR" >&2
    exit 1
fi

# 解析为绝对路径，确保 APP_DATA_DIR 指向项目外目录时也能正确备份
DATA_DIR="$(cd "$DATA_DIR" && pwd)"

backup_dir="${BACKUP_DIR:-$PROJECT_ROOT/backups}"
mkdir -p "$backup_dir"

ts="$(date +%Y%m%d-%H%M%S)"
tar -czf "$backup_dir/tg-signpulse-data-$ts.tar.gz" \
    -C "$(dirname "$DATA_DIR")" \
    "$(basename "$DATA_DIR")"

find "$backup_dir" -name 'tg-signpulse-data-*.tar.gz' -mtime +14 -delete

echo "备份完成: $backup_dir/tg-signpulse-data-$ts.tar.gz"
