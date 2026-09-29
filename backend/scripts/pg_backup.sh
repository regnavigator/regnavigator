#!/usr/bin/env bash
# Postgres 일별 백업 — docker compose 환경 기준
#
# 사용:
#   ./scripts/pg_backup.sh                          # ./backups/medi_<date>.sql.gz
#   BACKUP_DIR=/var/backups ./scripts/pg_backup.sh  # 디렉터리 변경
#   GCS_BUCKET=gs://<backup-bucket> ./scripts/pg_backup.sh   # 백업 후 GCS 업로드
#
# cron 예시 (매일 03:00 KST):
#   0 18 * * * cd /home/<user>/medi-back && ./scripts/pg_backup.sh >> /var/log/medi_backup.log 2>&1
#   (UTC 기준 — KST는 UTC+9이므로 18시 = 03시 KST)
#
# 보존 정책: 30일 이상된 백업은 자동 삭제 (RETENTION_DAYS env로 조정).

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
COMPOSE_SERVICE="${COMPOSE_SERVICE:-postgres}"
DB_USER="${POSTGRES_USER:-medi}"
DB_NAME="${POSTGRES_DB:-medi}"
GCS_BUCKET="${GCS_BUCKET:-}"

mkdir -p "$BACKUP_DIR"

TS=$(date -u +%Y%m%dT%H%M%SZ)
OUT="${BACKUP_DIR}/medi_${TS}.sql.gz"

echo "[backup] starting → $OUT"

# docker compose exec — 컨테이너 내에서 pg_dump
docker compose exec -T "$COMPOSE_SERVICE" \
    pg_dump -U "$DB_USER" -d "$DB_NAME" --clean --if-exists --no-owner \
    | gzip -9 > "$OUT"

SIZE=$(stat -c%s "$OUT" 2>/dev/null || stat -f%z "$OUT")
echo "[backup] done — $(numfmt --to=iec --suffix=B $SIZE 2>/dev/null || echo "${SIZE} bytes")"

# 보존 정책 — 오래된 백업 자동 삭제
if [ -n "$RETENTION_DAYS" ] && [ "$RETENTION_DAYS" != "0" ]; then
    find "$BACKUP_DIR" -name 'medi_*.sql.gz' -mtime +"$RETENTION_DAYS" -print -delete
fi

# GCS 업로드 (옵션)
if [ -n "$GCS_BUCKET" ]; then
    if ! command -v gsutil >/dev/null 2>&1; then
        echo "[backup] gsutil not found — skipping GCS upload" >&2
    else
        echo "[backup] uploading → ${GCS_BUCKET}/$(basename "$OUT")"
        gsutil cp "$OUT" "$GCS_BUCKET/"
    fi
fi

echo "[backup] complete"
