# HLS·CloudFront·Cloudflare Media Lab

이 문서는 로봇 데이터 파이프라인 프로젝트의 마지막 확장 실험이다. Managed Flink Notebook의 anomaly alert와 Slack 전달은 과거 AWS 인프라에서 이미 확인한 범위이므로 이번 실행에서는 중복 검증하지 않는다. 대신 짧은 VOD HLS 자산을 실제 AWS S3·CloudFront와 Cloudflare Worker 경로로 전달하고, primary 장애 시 secondary로 전환되는 미디어 edge 경로를 검증한다.

## 토폴로지

```text
ffmpeg VOD
   ├── private S3 eu-west-1 ── CloudFront primary ──┐
   │                                                 ├── Cloudflare Worker ── client
   └── private S3 us-east-1 ─ CloudFront secondary ──┘
```

- 두 S3 bucket은 public access를 차단하고 CloudFront Origin Access Control(OAC)만 `GetObject`를 허용한다.
- CloudFront는 `PriceClass_100`을 사용하고 playlist는 2~5초, segment는 최대 24시간 캐시한다.
- CloudFront response headers policy로 HLS 브라우저 클라이언트에 CORS를 제공한다.
- Cloudflare Worker는 `/media/*`를 primary CloudFront로 전달하고, 4xx/5xx·네트워크 예외가 발생하면 secondary CloudFront로 재시도한다.
- `?force_primary_failure=1`은 테스트용 controlled fault injection이다. 이 query는 origin으로 전달하지 않는다.
- `workers.dev` 주소를 사용하므로 별도 DNS zone·custom certificate를 생성하지 않는다.

CloudFront origin을 private S3와 OAC로 묶은 이유는 S3 URL 우회를 막고 배포 경로를 하나로 고정하기 위해서다. Cloudflare Worker는 Workers `fetch()` handler에서 upstream `Request`를 만들고 `Response`를 반환하는 edge proxy로 구현했다.

## 실행 순서

```bash
cd /Users/mason/Documents/Codex/2026-08-24/https-github-com-masondev1024-develope-project/work/robot-data-pipeline

export AWS_PROFILE=develope-test
export AWS_REGION=eu-west-1
export CLOUDFLARE_ACCOUNT_ID=<Cloudflare account id>
export MEDIA_RUN_ID=20260824
export MEDIA_DIR=/tmp/robot-media-lab-${MEDIA_RUN_ID}

python3 scripts/generate_hls_asset.py --output "$MEDIA_DIR"

terraform -chdir=terraform/media_lab init
terraform -chdir=terraform/media_lab apply \
  -var="run_id=${MEDIA_RUN_ID}" \
  -var="aws_profile=${AWS_PROFILE}" \
  -auto-approve

PRIMARY_BUCKET=$(terraform -chdir=terraform/media_lab output -raw primary_bucket)
SECONDARY_BUCKET=$(terraform -chdir=terraform/media_lab output -raw secondary_bucket)
PRIMARY_CF=$(terraform -chdir=terraform/media_lab output -raw primary_cloudfront_domain)
SECONDARY_CF=$(terraform -chdir=terraform/media_lab output -raw secondary_cloudfront_domain)

python3 scripts/upload_hls_asset.py \
  --profile "$AWS_PROFILE" \
  --primary-bucket "$PRIMARY_BUCKET" \
  --secondary-bucket "$SECONDARY_BUCKET" \
  --directory "$MEDIA_DIR"

npx --yes wrangler@4.125.0 deploy \
  --config media_lab/worker/wrangler.jsonc \
  --var "PRIMARY_ORIGIN:https://${PRIMARY_CF}" \
  --var "FALLBACK_ORIGIN:https://${SECONDARY_CF}" \
  --minify
```

CloudFront distribution은 전파 시간이 있으므로 두 domain이 `200`을 반환할 때까지 기다린 뒤 Wrangler가 출력한 `workers.dev` URL을 `WORKER_URL`로 기록한다.

```bash
export WORKER_URL=https://robot-media-lab-20260824.<account-subdomain>.workers.dev
python3 scripts/verify_media_lab.py \
  --primary-url "https://${PRIMARY_CF}" \
  --secondary-url "https://${SECONDARY_CF}" \
  --worker-url "$WORKER_URL" \
  --repeat 5 > /tmp/media-lab-evidence-${MEDIA_RUN_ID}.json
```

## 검증 기준

| 검증 | 통과 기준 |
|---|---|
| primary playlist | `200`, `#EXTM3U`, HLS segment 목록 존재 |
| secondary playlist | `200`, primary와 동일한 segment 구조 |
| primary/secondary segment | `200`, 빈 응답 아님, `video/mp2t` |
| Worker 정상 경로 | `X-Media-Lab-Origin: cloudfront-primary` |
| Worker 장애 전환 | `force_primary_failure=1`에서 `X-Media-Lab-Origin: cloudfront-secondary` |
| failover 정확성 | playlist와 첫 segment 모두 secondary에서 `200` |
| latency | route별 p95를 evidence JSON에 기록 |

실제 라이브 미디어 운영과 구분하기 위해 다음을 주장하지 않는다.

- live HLS ingest, encoder redundancy, DRM, low-latency HLS
- 실제 사용자 rebuffering ratio 또는 장시간 sustained bitrate
- Cloudflare Stream 서비스 사용량·실시간 미디어 품질
- DNS/Anycast 전환 시간이 포함된 multi-provider authoritative DNS failover

## Teardown 순서

Worker를 먼저 삭제하고 CloudFront/S3를 Terraform으로 제거한다. `force_destroy = true`와 1일 lifecycle은 이 실험이 다음 날까지 남지 않게 하는 보조 장치이며, 최종 판정은 직접 API 조회다.

```bash
npx --yes wrangler@4.125.0 delete \
  --config media_lab/worker/wrangler.jsonc \
  --force

terraform -chdir=terraform/media_lab destroy \
  -var="run_id=${MEDIA_RUN_ID}" \
  -var="aws_profile=${AWS_PROFILE}" \
  -auto-approve

aws cloudfront list-distributions --query \
  'DistributionList.Items[?Comment==`robot-media-lab-20260824 primary HLS distribution` || Comment==`robot-media-lab-20260824 secondary HLS distribution`].Id'
aws s3api list-buckets --query \
  'Buckets[?contains(Name, `robot-media-lab-20260824`)].Name'
aws ec2 describe-nat-gateways --filter Name=state,Values=pending,available,deleting
```

최종 감사에는 CloudFront distribution, S3 bucket/object, Cloudflare Worker, EIP/NAT/VPC, Terraform state를 포함한다. Tagging API가 삭제된 AWS ARN을 잠시 캐시할 수 있으므로 실제 서비스 control plane의 `NotFound`/빈 목록을 우선한다.

## 공식 참고

- [CloudFront private S3 origin과 OAC](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-restricting-access-to-s3.html)
- [Cloudflare Workers fetch handler](https://developers.cloudflare.com/workers/runtime-apis/handlers/fetch/)
- [Wrangler deploy 명령](https://developers.cloudflare.com/workers/wrangler/commands/workers/)

## 2026-08-24 실제 실행 증거

| 항목 | 결과 |
|---|---|
| HLS asset | `index.m3u8` 177B, `segment000.ts` 2,213,700B, `segment001.ts` 962,372B |
| Primary CloudFront | `dtpfm0ad1pp1d.cloudfront.net`, playlist/segment 200 |
| Secondary CloudFront | `d392hyu1ncxvwf.cloudfront.net`, playlist/segment 200 |
| Cloudflare Worker 정상 | `X-Media-Lab-Origin=cloudfront-primary`, 5/5 성공, playlist p95 238.63ms |
| Cloudflare Worker failover | `X-Media-Lab-Origin=cloudfront-secondary`, 5/5 성공, playlist p95 241.46ms |
| Direct CloudFront playlist p95 | primary 893.52ms, secondary 767.11ms |
| Worker 배포 | `robot-media-lab-20260824`, version `00535cdf-c324-4281-ad9c-9a8f747ac92d` |

첫 검증에서 Python 표준 라이브러리의 기본 `Python-urllib/3.x` User-Agent가 Cloudflare managed bot protection에 걸려 `1010/403`을 반환했다. `curl`과 브라우저형 User-Agent가 동일 경로에서 `200`인 것을 확인해 검증기를 실제 브라우저 HLS client class의 User-Agent로 수정했고, 이후 전체 검증이 통과했다. 이는 origin 장애가 아니라 synthetic probe의 client fingerprint 문제였다.

Flink Notebook anomaly alert와 Slack 전달은 과거 실행 증거가 있는 범위이므로 이번 Media Lab에서 재실행하지 않았다.

## 2026-08-24 teardown 실제 감사

검증 직후 Worker를 먼저 삭제하고 Terraform destroy를 실행했다.

| 감사 항목 | 결과 |
|---|---|
| Terraform media state | 18개 리소스 destroy 완료, `terraform state list` 빈 목록 |
| CloudFront | primary/secondary 모두 `NoSuchDistribution` |
| CloudFront 부속 리소스 | 실험용 cache policy, response headers policy, OAC 매칭 없음 |
| S3 | `robot-media-lab-20260824-*` bucket 매칭 없음 |
| Cloudflare Worker | API가 `This Worker does not exist`로 응답 |
| NAT Gateway | 활성화된 17개 AWS 리전 전체에서 `pending/available/deleting` 없음 |
| 미디어 실험 EIP/VPC | 실험 태그 기준 매칭 없음 |
| 당일 Cost Explorer | `$0`, `Estimated=true` — 청구 확정액이 아닌 지연된 조회값 |

따라서 이번 Media Lab은 HLS 경로와 controlled failover의 실제 증거를 남긴 뒤, 다음 실행까지 유지되는 AWS·Cloudflare 실행 리소스 없이 종료됐다. 단, AWS 비용 데이터는 반영 지연이 있으므로 최종 청구서와 동일하다고 표현하지 않는다.
