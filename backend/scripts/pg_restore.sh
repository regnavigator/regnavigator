#!/usr/bin/env bash
# Postgres 백업 복원 — docker compose 환경 기준
#
# 사용:
#   ./scripts/pg_restore.sh ./backups/medi_20260430T180000Z.sql.gz
#   ./scripts/pg_restore.sh gs://<backup-bucket>/medi_20260430T180000Z.sql.gz
#
# 주의: --clean --if-exists로 덤프했기 때문에 기존 객체가 모두 drop 후 복원됨.
# 운영 중 호출 시 thread state 손실됨 — staging에서만 또는 maintenance window에.

set -euo pipefail

if [ $# -ne 1 ]; then
    echo "usage: $0 <backup.sql.gz | gs://...>" >&2
    exit 2
fi

SRC="$1"
COMPOSE_SERVICE="${COMPOSE_SERVICE:-postgres}"
DB_USER="${POSTGRES_USER:-medi}"
DB_NAME="${POSTGRES_DB:-medi}"

# GCS 다운로드 (필요 시)
TMP=""
if [[ "$SRC" =~ ^gs:// ]]; then
    if ! command -v gsutil >/dev/null 2>&1; then
        echo "gsutil not found" >&2; exit 1
    fi
    TMP=$(mktemp --suffix=.sql.gz)
    echo "[restore] downloading $SRC → $TMP"
    gsutil cp "$SRC" "$TMP"
    SRC="$TMP"
fi

if [ ! -f "$SRC" ]; then
    echo "file not found: $SRC" >&2; exit 1
fi

echo "[restore] WARNING: 기존 DB 객체가 모두 drop됩니다."
echo "[restore] DB: $DB_NAME / source: $SRC"
read -r -p "계속하시겠습니까? (yes/no) " ans
if [ "$ans" != "yes" ]; then
    echo "aborted"; exit 1
fi

echo "[restore] starting..."
gunzip -c "$SRC" | docker compose exec -T "$COMPOSE_SERVICE" \
    psql -U "$DB_USER" -d "$DB_NAME" --quiet

echo "[restore] done"

if [ -n "$TMP" ] && [ -f "$TMP" ]; then
    rm -f "$TMP"
fi
