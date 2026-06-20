#!/usr/bin/env bash
set -euo pipefail

backup_dir="${BACKUP_DIR:-./backups}"
mkdir -p "$backup_dir"

ts="$(date +%Y%m%d-%H%M%S)"
tar -czf "$backup_dir/tg-signpulse-data-$ts.tar.gz" data

find "$backup_dir" -name 'tg-signpulse-data-*.tar.gz' -mtime +14 -delete

echo "备份完成: $backup_dir/tg-signpulse-data-$ts.tar.gz"
