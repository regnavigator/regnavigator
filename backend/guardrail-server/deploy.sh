#!/usr/bin/env bash
# 가드레일 게이트 서비스 재현 배포 — DGX(spark-e125)에서 실행.
# NER(:8090) + 의도 분류(:8091) 를 systemd 상시 서비스로. ad-hoc ssh 대체.
#
# 사용:  guardrail-server/ 를 DGX 로 옮긴 뒤 그 안에서
#   INSTANCE_API_KEY=<키> ./deploy.sh
#
# ※ git clone/pull 로 받았는데 "Permission denied" 면 실행권한이 없는 것:
#     bash deploy.sh      (또는 chmod +x deploy.sh)
#   저장소에는 100755 로 올려두었으나(2026-08-02), 그 이전에 받은 체크아웃이나
#   실행비트를 보존하지 않는 환경에서는 위처럼 실행한다.
#
# 멱등 — 재실행 안전(코드·유닛 갱신 + 재시작). 모델은 최초 1회만 다운로드.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
# ⚠️ 기본 경로는 **실제 배포 상태와 일치**해야 한다(2026-07-25 정정). 구 기본값
# ($HOME/Desktop/guardrail-ner · $HOME/Desktop/openlaw-search/.venv)은 DGX 에
# 존재하지 않는 경로였다 — 그대로 실행하면 5단계에서 낡은 유닛 파일을 라이브 위에
# sudo cp 해 NER·intent **양쪽이 기동 실패**한다. 경로가 또 바뀌면 여기와
# guardrail-{ner,intent}.service 를 **같이** 고칠 것.
DEST="${GUARDRAIL_DIR:-$HOME/Desktop/working/guardrail-ner}"
VENV="${GUARDRAIL_VENV:-$HOME/Desktop/working/github/openlaw-etl/.venv}"   # GB10 검증 torch 재사용
VP="$VENV/bin/python"
KEY="${GUARDRAIL_API_KEY:-${INSTANCE_API_KEY:-}}"
NER_THRESHOLD="${NER_THRESHOLD:-0.4}"

[ -x "$VP" ] || { echo "!! venv 없음: $VP (GUARDRAIL_VENV 지정)"; exit 1; }
[ -n "$KEY" ] || { echo "!! INSTANCE_API_KEY(또는 GUARDRAIL_API_KEY) 필요"; exit 1; }

echo "== 1. torch/cuda 검증 =="
"$VP" -c "import torch;assert torch.cuda.is_available();print('torch',torch.__version__,'cuda OK')"

echo "== 2. 의존 설치(핀) =="
"$VP" -m pip install -q -r "$HERE/requirements.txt"

echo "== 3. 코드 배치 =="
mkdir -p "$DEST"
# ⚠️ 저장소를 DEST 에 직접 clone/pull 해 쓰는 운용에서는 HERE == DEST 다.
# 그때 `cp a a` 는 "are the same file" 로 실패하고 `set -e` 가 스크립트를
# 통째로 중단시킨다(실측 2026-08-02 DGX 회신). 같은 경로면 복사 자체가 불필요.
if [ "$HERE" -ef "$DEST" ]; then
  echo "   (HERE == DEST — 저장소에서 바로 실행, 복사 생략)"
else
  cp "$HERE/serve.py" "$HERE/serve_intent.py" "$DEST/"
fi
printf 'INSTANCE_API_KEY=%s\nNER_THRESHOLD=%s\n' "$KEY" "$NER_THRESHOLD" > "$DEST/guardrail.env"
chmod 600 "$DEST/guardrail.env"

echo "== 4. 모델 사전 다운로드(최초 1회) =="
"$VP" - <<PY
from huggingface_hub import snapshot_download
for m in ("OpenMed/privacy-filter-multilingual","Qwen/Qwen3.5-0.8B"):
    print("download", m); snapshot_download(m)
print("models ready")
PY

echo "== 5. systemd 유닛 설치 + 기동 =="
for u in guardrail-ner guardrail-intent; do
  sudo cp "$HERE/$u.service" /etc/systemd/system/
done
sudo systemctl daemon-reload
sudo systemctl enable guardrail-ner guardrail-intent
# ⚠️ `enable --now` 는 **이미 켜져 있으면 재시작하지 않는다** → 새 코드가 로드되지
# 않고 옛 프로세스가 그대로 돈다(실측 2026-08-02: 운영자가 매번 수동 restart 해야
# 했다). 배포 스크립트는 항상 새 코드를 반영해야 하므로 restart 로 강제한다.
sudo systemctl restart guardrail-ner guardrail-intent

echo "== 6. 헬스체크 =="
for p in 8090 8091; do
  for i in $(seq 1 20); do
    sleep 4
    R=$(curl -s -m 8 -H "X-API-Key: $KEY" "http://localhost:$p/health" 2>/dev/null) || true
    [ -n "$R" ] && { echo "  :$p OK — $R"; break; }
  done
done
echo "완료. medirag-back → PII_NER_API_URL=http://<DGX>:8090 · INTENT_API_URL=http://<DGX>:8091"
