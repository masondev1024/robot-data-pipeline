# PRISM 운영자 사용 가이드

이 문서는 현장(고객사 PoC, 본선 부스, 전시) 운영자가 PRISM 콘솔 앞에서
어떤 순서로 어떤 결정을 내리는지 정의한다. 시연 4분 timeline 과 동일한 구조.

## 부팅 확인 (시연 시작 30초 전)

```bash
cd prism/
docker compose ps         # app 상태 healthy 확인
docker compose logs app | tail -20
```

브라우저 접속: <http://localhost:8501>
콘솔 좌상단 "PRISM" 로고가 보이면 정상.

## 4분 시연 timeline (본선 5/22 기준)

| 시각 | 마커 | 운영자 동작 | 예상 결과 |
|---|---|---|---|
| 0:00 | 1. 정상 운영 | 콘솔 진입, sensor 11개 라이브 차트 확인 | 모든 robot 정상, defect=0 |
| 0:15 | 2. 이상 감지 | tool_age, vibration 상승 watch | XGBoost 6-class 가 `tool_wear_imminent` 라벨 |
| 0:30 | 3. 인과 v1 카드 출현 | **"절삭유 +5% 추천" 카드** 검토 | DoWhy CE=0.78, refute pass 표시 |
| 0:45 | 3. 인간 결정 = **"보류"** | "보류" 버튼 클릭 (적용 X) | timeline 에 보류 이벤트 기록 |
| 1:00 | 4. 시뮬 가속 | "3시간 fast-forward" 버튼 클릭 | 보류 시 결함 진행 예측 그래프 |
| 1:15 | 5. 불량 발생 | defect=1 row 진입 확인 | 보류 결정의 결과 시각화 |
| 1:30 | 6. 인과 v2 카드 | **CE 0.78 → 0.71** 재추정 | 학습 자산 (v1→v2 비교 카드) |

## 마커별 콘솔 화면 위치

| 마커 | 콘솔 섹션 | 라이브 wiring 여부 |
|---|---|---|
| 1 | 좌측 sensor 11 stream | ✅ DuckDB 직접 |
| 2 | 중앙 XGBoost 라벨 | ✅ `src/ml/local_predictor.py` 즉시 호출 |
| 3 | 우측 인과 카드 | 사전 녹화 (cache_replay) — 본선 안정성 |
| 4 | fast-forward 시뮬 패널 | ✅ DoWhy `do(coolant_temp +5%)` 실시간 |
| 5 | defect timeline | ✅ DuckDB query |
| 6 | v1↔v2 비교 카드 | 사전 녹화 (causal_refute_v2.json) |

라이브 wiring 4개 + 사전 녹화 2개 구조 → "동작은 한다, 시연만 결정론적으로 짠 것"
방어 narrative.

## 장애 대응

| 증상 | 원인 | 조치 |
|---|---|---|
| 마커 3 카드가 안 뜸 | Bedrock 호출 실패 + offline=false | `.env` 에 `BEDROCK_OFFLINE=true` 설정 후 `docker compose restart app` |
| sensor stream 멈춤 | DuckDB 락 | `docker compose restart app` (DuckDB 파일은 보존) |
| 8501 포트 충돌 | 다른 streamlit 인스턴스 | `.env` 의 `STREAMLIT_PORT=8502` 변경 후 재기동 |
| 마커 4 fast-forward 무반응 | DoWhy 임포트 실패 | 컨테이너 로그 확인. 보통 graphviz 의존성 → 이미지 재빌드 |

## 시연 후 정리

```bash
docker compose down       # 컨테이너 정리 (DuckDB 파일은 호스트 ../data/ 에 보존)
git status               # 결정론적 시연이면 diff 0
```

## 현장 PoC 인수인계 체크리스트

- [ ] 노트북 / 미니 서버에 Docker Desktop 24+ 설치 확인
- [ ] `.env` 의 `BEDROCK_OFFLINE` 정책 결정 (인터넷 가능하면 false, 없으면 true)
- [ ] `data/prism_demo.duckdb` 초기 상태 확인 (생산 라인별 seed 다를 수 있음)
- [ ] 사내망 접근 URL 공지 (`http://<host-ip>:8501`)
- [ ] 운영자에게 마커 6단계 timeline 숙지시킴
