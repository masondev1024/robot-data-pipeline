# legacy/ — 학습·발표 자료 아카이브

이 디렉토리는 **PRISM AI 인과추론 레이어를 legacy 대규모 데이터 파이프라인에 접목하는 통합 작업(2026-05-23)** 이후
production 코드·인프라가 모두 루트로 이동되고, **학습·발표 참고자료만** 남은 상태다.

## 현재 보존되는 자산

| 파일/디렉토리 | 내용 |
|---|---|
| `학습자료/` | 데이터 엔지니어링 학습 노트 |
| `프로젝트 정보/` | 프로젝트 메타데이터·기록 |
| `발표자료.md` | 데이터 파이프라인 발표 원고 (PRISM 이전) |
| `README_robot_data_pipeline.md` | 옛 robot-data-pipeline 단독 README (역사 참고) |
| `CLAUDE.md` | 옛 운영 매뉴얼 (루트 `CLAUDE.md` 의 가드레일 출처. **삭제 금지** — 통합 시 keep/drop 판단 기준) |

## 이주 완료된 production 자산 (위치)

| 옛 경로 | 새 경로 |
|---|---|
| `legacy/terraform/` | [`terraform/`](../terraform/) |
| `legacy/dags/` | [`dags/`](../dags/) |
| `legacy/helm/` | [`helm/`](../helm/) |
| `legacy/k8s/` | [`k8s/`](../k8s/) |
| `legacy/sql/` | [`sql/`](../sql/) |
| `legacy/grafana/` | [`grafana/`](../grafana/) |
| `legacy/docker/` | [`docker/`](../docker/) |
| `legacy/scripts/*` | [`scripts/`](../scripts/) (PRISM scripts 와 공존) |
| `legacy/비용절감플랜/` | [`비용절감플랜/`](../비용절감플랜/) |
| `legacy/src/api/` | [`src/api/`](../src/api/) |
| `legacy/src/lambda/` | [`src/lambda/`](../src/lambda/) |
| `legacy/src/generator/*` | [`src/generator/`](../src/generator/) (PRISM `cnc_stream.py` 와 공존) |
| `legacy/src/ml/*` | [`src/ml/`](../src/ml/) (PRISM `local_predictor.py` 와 공존) |
| `legacy/src/common/athena.py` | [`src/common/athena.py`](../src/common/) |
| `legacy/tests/{api,etl,generator,lambda,ml}/` | [`tests/`](../tests/) (PRISM tests 와 서브디렉토리 분리 공존) |
| `legacy/docs/plan/` | [`docs/plan/`](../docs/plan/) |

## 통합 설계 참조

`docs/superpowers/specs/2026-05-23-prism-production-integration-design.md`
