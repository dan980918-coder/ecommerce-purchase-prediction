# Deployment

## 현재 상태

**Streamlit Community Cloud에 배포되어 있다.**

- 배포 URL: https://crm-targeting-intelligence-jydu6dct3hhzdprekfzz3k.streamlit.app
- 엔트리포인트: `app/Home.py`
- 배포된 앱은 `data/dashboard/*.csv`(약 15KB, 사전 집계된 소용량 파일)만
  읽는다(`src/dashboard/data.py` 참고) — 원본 데이터·`data/processed/*.duckdb`
  (3GB+, gitignore 대상)는 배포 환경에 포함하지 않는다(PROJECT_GUIDELINES.md의
  GitHub 공개 금지 목록(.gitignore 항목) 참고).

## Streamlit Community Cloud 배포 방법 (GitHub 연동)

1. https://share.streamlit.io 에서 GitHub 계정으로 로그인
2. "New app" → 이 저장소(`dan980918-coder/crm-targeting-intelligence`)와
   브랜치(`main`), 엔트리포인트(`app/Home.py`)를 지정
3. Deploy 클릭 — `requirements.txt` 기준으로 의존성을 자동 설치하고,
   `.streamlit/config.toml`의 테마 설정을 그대로 적용해 빌드한다
4. 이후 `main` 브랜치에 push할 때마다 자동으로 재배포된다(수동 재배포 불필요,
   보통 1\~2분 소요)

## Secrets 설정 (선택 — LLM API 키)

AI CRM Report 페이지는 API 키 없이도 mock 백엔드로 동작하므로 필수는 아니다.
실제 LLM 호출을 쓰려면 Streamlit Cloud 앱 관리 화면의 "Settings → Secrets"에
로컬 `.env`와 동일한 키를 TOML 형식으로 추가한다:

```toml
ANTHROPIC_API_KEY = "sk-ant-..."
# 또는
OPENAI_API_KEY = "sk-..."
```

`src/llm/client.py`의 `get_available_backend()`가 이 값을 자동으로 감지해
mock → 실제 LLM 백엔드로 전환한다. API 키는 절대 저장소에 커밋하지 않는다
(PROJECT_GUIDELINES.md의 GitHub 공개 금지 목록, `.gitignore`의 `.env*`).

## 로컬 실행 순서

### 1. 환경 준비

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 원본 데이터 확보 (비공개 — 직접 다운로드 필요)

공식 출처(https://recsys.synerise.com/data-set)에서 `synerise_dataset.tar.gz`
를 받아 압축을 풀고 `data/raw/synerise_dataset/`에 위치시킨다. 상세 절차는
`reports/phase1_download_log.md` 참고. 원본 데이터는 라이선스(CC BY-NC 4.0)상
이 저장소에 포함되어 있지 않다.

### 3. 데이터마트 빌드

```bash
python3 scripts/build_database.py
```

`data/processed/crm.duckdb`에 staging → intermediate → mart(11개) 전체가
빌드된다 (약 5\~10분 소요, page_visit 1.99억 행 처리 포함).

### 4. 모델 학습 및 타기팅 시뮬레이션 (선택)

```bash
python3 scripts/train_model_a.py
python3 scripts/train_model_b.py
python3 scripts/build_targeting_simulation.py
```

### 5. 대시보드용 데이터 내보내기 + 실행

```bash
python3 scripts/build_dashboard_data.py
streamlit run app/Home.py
```

`http://localhost:8501`에서 확인.

### 6. LLM CRM 리포트 (선택)

API 키 없이도 mock 백엔드로 동작한다.

```bash
python3 scripts/generate_crm_report.py
```

실제 LLM을 쓰려면 `.env.example`을 `.env`로 복사한 뒤
`ANTHROPIC_API_KEY` 또는 `OPENAI_API_KEY`를 채운다.

### 7. 테스트

```bash
pytest tests/ -q
```
