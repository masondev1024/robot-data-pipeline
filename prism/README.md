# prism/ — Deployable MVP Stack

PRISM 운영 콘솔의 **현장 배포 단위**. AWS·EKS·Airflow 없이 노트북 1대 또는 단일 호스트에서
docker compose 한 줄로 가동된다.

## 한 줄 부팅 (시연·현장 공통)

```bash
cd prism/
cp .env.example .env       # Bedrock 키 등 입력 (offline 시연이면 그대로 두기)
docker compose up --build
```

부팅 후:
- Streamlit 운영 콘솔 (Demo): <http://localhost:8501>
- Streamlit 운영 콘솔 (Live): <http://localhost:8502>
- Streamlit 운영 콘솔 (Operator): <http://localhost:8503>
- CNC generator: docker network 안에서 tick 발신 → Streamlit 이 DuckDB 로 직접 적재

기존 8502 콘솔을 보존하고 Operator-first 새 화면을 별도로 확인할 때는 루트에서 직접 실행:

```bash
PYTHONHASHSEED=2026 PRISM_MODE=demo streamlit run apps/prism_operator_demo.py --server.port 8503
```

- Operator-first 콘솔: <http://localhost:8503>

## 왜 가벼운 스택인가

본선 시연·현장 PoC 의 본질 기여는 **인과 카드 + 운영자 결정 루프 + 시뮬레이션 fast-forward**
지, 1000대 robot 을 KDS/Firehose/Flink 로 실시간 처리하는 게 아니다. 1000대 production
확장 패턴은 `legacy/` 가 reference 로 보존한다.

| 기존 robot-data-pipeline | PRISM MVP |
|---|---|
| Kinesis Data Streams (2 shard) | docker network 안 generator → Streamlit 직접 (CNC fleet 10대) |
| Firehose → S3 Parquet (Iceberg) | DuckDB 단일 파일 (`data/prism_demo.duckdb`) |
| Athena workgroup + partition projection | DuckDB SQL in-process |
| SageMaker Endpoint (XGBoost) | `src/ml/local_predictor.py` 로컬 XGBoost |
| Airflow 3 DAG | 시연 timeline 은 Streamlit 안 마커 5개 |
| Grafana fleet 모니터링 | Streamlit 운영 콘솔이 batch 결과 시각화 |
| 월 운영비 \~\$1,200 (EKS+Karpenter+ALB+KDS+Firehose+SageMaker) | 노트북 1대 + Bedrock on-demand \~\$10-20 |

## 구성

```
prism/
├── README.md              ← 이 파일
├── docker-compose.yml     ← Streamlit + generator 컨테이너 정의
├── Dockerfile.app         ← 기존 8502 Streamlit 이미지 (apps/prism_demo.py 실행)
├── Dockerfile.generator   ← CNC stream generator 이미지
├── requirements.txt       ← prism 컨테이너 공통 Python deps
├── .env.example           ← Bedrock·시연 옵션 템플릿
└── operator-guide.md      ← 현장 운영자용 사용 가이드 (마커별 시나리오)
```

런타임이 참조하는 외부 디렉토리(루트 기준):
- `apps/prism_demo.py` — 기존 8501(Demo)/8502(Live) Streamlit entry point
- `apps/prism_operator_demo.py` — 새 8503 Operator-first Streamlit entry point
- `src/orchestration/` — 인과 DAG, 카드, supervisor, llm_cache
- `src/generator/cnc_stream.py` — CNC stream tick
- `src/ml/local_predictor.py` — 로컬 6-class XGBoost
- `src/common/bedrock.py` — Bedrock invoke (offline 시 cache_replay 사용)
- `assets/` — `xgb_6class.pkl`, `cache_replay.jsonl`, `causal_refute_v2.json`
- `data/prism_demo.duckdb` — DuckDB 적재 위치 (read-write mount)

## 환경 변수 (.env)

| 키 | 기본값 | 용도 |
|---|---|---|
| `PRISM_MODE` | `demo` | `demo` = 결정론적 시연 (`PYTHONHASHSEED=2026` 강제) |
| `BEDROCK_REGION` | `ap-northeast-2` | Bedrock Claude 호출 region |
| `PRISM_OFFLINE` | `1` | `1` 이면 cache_replay 만 사용 (네트워크 없이도 시연) |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | — | Bedrock 호출 시. offline 모드면 불필요 |
| `DEMO_PORT` | `8501` | 호스트 포트 (Demo) |
| `LIVE_PORT` | `8502` | 호스트 포트 (Live) |
| `OPERATOR_PORT` | `8503` | 호스트 포트 (Operator) |

## 시연 안정성 — offline 모드

본선·전시 부스에서 네트워크가 불안정해도 결정론적 결과 보장:

```bash
PRISM_OFFLINE=1 docker compose up
```

`assets/cache_replay.jsonl` 의 사전 녹화된 Bedrock 응답을 그대로 재생한다.
`llm_cache.py` 가 hash 키로 lookup → cache miss 면 `CacheReplayError` 즉시 raise (조용한 실패 금지).

## 현장 배포 (고객사 PoC)

1. 노트북 / 미니 서버에 Docker 설치.
2. 이 저장소 clone 또는 `prism/` 디렉토리 + `apps/`, `src/`, `assets/`, `data/` rsync.
3. `.env` 에 고객사 Bedrock 키 또는 `PRISM_OFFLINE=1` 설정.
4. `docker compose up -d` 후 노트북 IP:8502 사내망 공유.
5. 운영자는 `operator-guide.md` 따라 마커별 의사결정 실행.

기존 로컬 `.env`의 `BEDROCK_OFFLINE=true`는 호환을 위해 계속 허용하지만, 신규 배포는 반드시 `PRISM_OFFLINE=1`을 사용한다.

## Hosted portfolio deployment

This is a small, single-host **public portfolio** deployment: Caddy terminates
HTTPS and applies Basic Auth, while `operator-app` remains on the internal
Compose network. It has no AWS credentials, cloud deployment step, or
production control-plane access. Completing the steps below makes a host
**ready**; it does not claim the demo is actually deployed until that host's
DNS, TLS, authentication, and health checks have passed.

Host prerequisites: a Linux host with Docker Engine plus the Docker Compose
plugin, a bare public FQDN whose DNS A/AAAA records already point to the host,
and inbound TCP 80/443 (plus UDP 443 when HTTP/3 is wanted). Set
`PUBLIC_DOMAIN` to the FQDN only—never a scheme, port, path, or value containing
whitespace. Keep the environment file host-only, outside this repository, and
never commit it or place it in a shell profile.

Create `/etc/prism-public.env` interactively with only the public domain,
ACME email, Basic Auth user, and a bcrypt hash. Generate the hash locally (for
example, `docker run --rm caddy:2.10.2 caddy hash-password --algorithm bcrypt`)
and paste it into the file; do not put an actual password or hash in a command
history. Restrict it before adding values:

```bash
sudo install -o root -g root -m 600 /dev/null /etc/prism-public.env
sudoedit /etc/prism-public.env
# PUBLIC_DOMAIN=prism.example.com
# CADDY_ACME_EMAIL=ops@example.com
# CADDY_BASIC_AUTH_USER=reviewer
# CADDY_BASIC_AUTH_HASH='$2b$...'
```

From the repository root, validate the file before creating or changing any
containers. The validator parses values without sourcing the file and never
prints the hash.

```bash
sudo bash prism/scripts/prepare-public-demo.sh --env-file /etc/prism-public.env
sudo docker compose --env-file /etc/prism-public.env -f prism/docker-compose.public.yml config --quiet
sudo docker compose --env-file /etc/prism-public.env -f prism/docker-compose.public.yml up -d --build --wait
```

After DNS and certificate issuance complete, first confirm that anonymous
access is rejected, then authenticate without placing a password in the
command line (curl will prompt for it):

```bash
curl -I https://prism.example.com
# Expect: HTTP/2 401
curl -u reviewer https://prism.example.com/_stcore/health
# Expect a successful health response after entering the password interactively.
```

Before an image or Compose upgrade, take a recoverable copy of the deterministic
demo data volume. The local build identity is not a registry digest. Record
release registry digest references separately in the change record. Do not reset
a volume as an upgrade shortcut.

```bash
sudo mkdir -p backups
sudo docker volume inspect prism-public-data
sudo docker run --rm -v prism-public-data:/data:ro -v "$PWD/backups":/backup busybox \
  tar czf /backup/prism-public-data-$(date +%F).tgz -C /data .
sudo docker image inspect --format '{{.Id}}' prism-public-operator:local
```

To reset the deterministic demo dataset, review the backup and run this exact,
explicitly destructive command. It stops and removes only `operator-app`, then
removes only the literal `prism-public-data` volume before restarting the
already selected image release with `--no-build` and waiting for the public
Compose project.

```bash
sudo bash prism/scripts/reset-public-demo-data.sh --env-file /etc/prism-public.env \
  --confirm-reset RESET_PRISM_PUBLIC_DEMO_DATA
```

For a release or rollback, put both previously approved immutable image
references in the protected host file, then pull them before starting. `--no-build`
is deliberate: it prevents a rollback from silently rebuilding the current
source tree instead of using the selected release artifacts.

```bash
sudoedit /etc/prism-public.env
# PRISM_PUBLIC_OPERATOR_IMAGE=registry.example/prism-operator@sha256:<previous-approved-digest>
# PRISM_PUBLIC_CADDY_IMAGE=registry.example/prism-caddy@sha256:<previous-approved-digest>
sudo docker compose --env-file /etc/prism-public.env -f prism/docker-compose.public.yml pull
sudo docker compose --env-file /etc/prism-public.env -f prism/docker-compose.public.yml up -d --no-build --wait
```

Verify the same anonymous-401 and authenticated-health checks after a release
or rollback. Teardown is an operator decision: run
`sudo docker compose --env-file /etc/prism-public.env -f prism/docker-compose.public.yml down`
only after preserving the data-volume backup and removing the host DNS record.

## 1000대 robot production 확장 경로

이 MVP 가 그대로 production 으로 가지 **않는다**. scale-up 시 `legacy/` 자산을 활용:

- generator → `legacy/k8s/generator/statefulset.yaml` (HPA + Karpenter)
- 적재 → `legacy/terraform/modules/data_pipeline/kinesis.tf` (KDS 2 shard)
- batch → `legacy/dags/robot_daily_etl.py` (Bronze→Silver→Gold)
- ML → `legacy/src/ml/train.py` (SageMaker XGBoost)
- 알림 → `legacy/src/lambda/alert_handler.py` (Slack webhook)

발표 슬라이드 1장: "PRISM MVP (현재) → 1000대 production (확장)" 양방향 화살표.
