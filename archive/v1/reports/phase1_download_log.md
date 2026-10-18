# Phase 1 - 8.1 데이터 다운로드 기록

## 공식 출처 확인

- 공식 데이터 페이지: https://recsys.synerise.com/data-set (Synerise 공식 도메인)
- 공식 코드 저장소: https://github.com/Synerise/recsys2025 (코드: MIT License, 데이터 라이선스는 미표시 — 데이터 라이선스는 공식 데이터 페이지에 별도 명시됨)
- 다운로드 링크는 페이지 DOM에서 직접 추출한 실제 `<a href>` 값이며, 로그인/등록 절차 없이 직접 접근 가능함을 HEAD 요청으로 확인함 (HTTP/2 200).

## 라이선스 (원문)

> "Universal Behavioral Modeling Dataset © 2025 by Synerise SA is licensed under Creative Commons Attribution-NonCommercial 4.0 International. To view a copy of this license, visit https://creativecommons.org/licenses/by-nc/4.0/"

출처: https://recsys.synerise.com/summary#download (2026-08-05 확인)

PROJECT_GUIDELINES.md에 기재된 `CC BY-NC 4.0`과 일치함을 확인.

## 다운로드한 파일

| 항목 | 값 |
|---|---|
| 파일명 | synerise_dataset.tar.gz |
| 구분 | 원본(raw) 데이터셋 |
| 다운로드 URL | https://data.recsys.synerise.com/dataset/synerise_dataset.tar.gz |
| 저장 경로 | data/raw/synerise_dataset.tar.gz (git 추적 제외) |
| 압축 파일 크기 (실측) | 2,062,884,710 bytes (≈ 1.92 GB) |
| 압축 파일 크기 (HEAD 응답 Content-Length, 다운로드 전 확인) | 2,062,884,710 bytes — 실측과 일치 |
| 압축 해제 후 예상 크기 (gzip 헤더 기준) | 2,603,796,480 bytes (≈ 2.42 GiB / 2.60 GB) |
| 파일 형식 | gzip 압축 tar (`.tar.gz`) |
| 서버 Last-Modified | 2025-11-12 12:29:52 GMT |
| 다운로드 날짜 | 2026-08-05 |
| sha256 체크섬 | e90b8fded8bc7a87b8c51ced7d5eead75f6deb09852ea701f5f22934e78b66e7 |
| 라이선스 | CC BY-NC 4.0 (위 원문 참조) |
| 공식 출처 | https://recsys.synerise.com/data-set |

## 참고: 미다운로드 파일 (필요 시 추후 진행)

| 항목 | 값 |
|---|---|
| 파일명 | challenge_dataset.tar.gz |
| 구분 | RecSys 2025 Challenge용 전처리 데이터셋 |
| 다운로드 URL | https://data.recsys.synerise.com/dataset/challenge_dataset.tar.gz |
| 압축 파일 크기 (HEAD 응답) | 1,441,649,865 bytes (≈ 1.34 GB) |
| 서버 Last-Modified | 2025-11-12 12:35:16 GMT |
| 다운로드 여부 | 미다운로드 — PROJECT_GUIDELINES.md 8.1 원칙(원본 데이터 구조 우선 확인)에 따라 원본만 우선 다운로드함 |

## 비고

- 원본 데이터 압축 해제 및 내부 파일 구조 검사는 8.2 단계에서 진행 예정.
- 데이터 사용 원칙(PROJECT_GUIDELINES.md 2번)에 따라 `data/raw/`는 `.gitignore`에 등록되어 GitHub에 업로드되지 않음 (`git check-ignore` 확인 완료).
