#!/usr/bin/env bash
# Synerise RecSys Challenge 2025 공식 원본 데이터셋 다운로드 및 무결성 확인
# 공식 출처: https://recsys.synerise.com/data-set
set -euo pipefail

cd "$(dirname "$0")/.."   # v2/
mkdir -p data/raw

URL="https://data.recsys.synerise.com/dataset/synerise_dataset.tar.gz"
ARCHIVE="data/synerise_dataset.tar.gz"
EXPECTED_SHA256="e90b8fded8bc7a87b8c51ced7d5eead75f6deb09852ea701f5f22934e78b66e7"

echo "== 다운로드 전 디스크 공간 =="
df -h ~

echo "== 다운로드 시작: $URL =="
curl -L --fail -o "$ARCHIVE" "$URL"

echo "== 압축 파일 크기 =="
ls -la "$ARCHIVE"

echo "== SHA-256 확인 =="
ACTUAL_SHA256=$(shasum -a 256 "$ARCHIVE" | awk '{print $1}')
echo "expected: $EXPECTED_SHA256"
echo "actual:   $ACTUAL_SHA256"
if [ "$ACTUAL_SHA256" != "$EXPECTED_SHA256" ]; then
  echo "체크섬 불일치! 중단." >&2
  exit 1
fi
echo "체크섬 일치 확인."

echo "== 압축 해제: data/raw/ =="
tar -xzf "$ARCHIVE" -C data/raw/

echo "== 압축 해제 결과 =="
find data/raw -type f -exec ls -la {} \;

echo "== 압축 파일 삭제 (공간 확보) =="
rm -f "$ARCHIVE"
echo "삭제 완료. 재다운로드 시 이 스크립트를 재실행하면 동일 URL에서 다시 받을 수 있음: $URL"

echo "== 다운로드 후 디스크 공간 =="
df -h ~
