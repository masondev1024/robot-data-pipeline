. Data Generator의 논리적 모순 (Phase 1.5)
현재 계획: 서울시 따릉이 API를 5초 간격으로 Polling하여 Kinesis로 전송.

비판 (팩트 폭격): 기존 래플 프로젝트에서는 Locust를 통해 초당 수천 건의 '동시 접속 트래픽'을 발생시켜 EKS HPA와 Karpenter의 스케일 아웃 로직을 증명했습니다. 그러나 현재 계획대로 단일 API를 5초마다 Polling한다면, 발생하는 데이터는 기껏해야 분당 수십~수백 건에 불과합니다. 이 정도의 데이터 트래픽(Throughput)으로는 Kinesis의 샤드 분산 처리, Flink의 스트리밍 부하, S3 파티셔닝의 효용성을 전혀 증명할 수 없습니다. 빅데이터 파이프라인 인프라를 구축해 놓고 텍스트 파일 몇 줄 옮기는 수준으로 전락합니다.

개선안 (스케일업 모킹):

따릉이 API 데이터는 초기 스키마(Seed) 및 x,y 좌표의 난수 범위를 지정하는 용도로만 한 번 읽어옵니다.

src/generator/app.py를 파이썬의 multiprocessing이나 asyncio를 활용한 대규모 동시성 제너레이터로 수정하십시오.

"가상의 로봇 10,000대가 동시에 초당 1회씩 센서 데이터를 뿜어내는 상황"을 코드로 시뮬레이션하여 Kinesis에 물리적인 부하(Write ProvisionedThroughputExceeded)가 발생하기 직전까지 밀어 넣어야 합니다. 그래야 파이프라인의 진가가 드러납니다.

2. KDF의 Parquet 변환 데드락 (Phase 1.4)
현재 계획: Kinesis Data Firehose(KDF) 설정 시 AWS Glue Data Catalog 테이블 포맷을 참조하여 Parquet으로 변환.

비판: Terraform 프로비저닝 순서 상 심각한 데드락(Deadlock)이 발생합니다. KDF가 JSON을 Parquet으로 변환하려면 **사전에 정의된 대상 테이블 스키마(Glue Table)**가 존재해야 합니다. 그러나 계획표를 보면 Glue/Athena DDL 작성은 Phase 2.1에 배치되어 있습니다. Phase 1에서 Terraform을 돌릴 때 참조할 Glue Table이 없어 프로비저닝이 실패합니다.

개선안:

modules/data_pipeline/glue.tf를 Phase 1.4 이전에 추가하십시오.

Terraform의 aws_glue_catalog_database와 aws_glue_catalog_table 리소스를 사용하여 Bronze 레이어의 스키마를 코드로 먼저 강제 선언해야 Firehose가 이를 바라보고 Parquet 변환을 수행할 수 있습니다.

3. VPC 네트워크 비용 및 보안 안티패턴 (Phase 0.1)
현재 계획: 기존 래플 프로젝트의 network.tf 재사용 (퍼블릭/프라이빗 서브넷, NAT Gateway 구조).

비판: 프라이빗 서브넷에 위치한 EKS Pod(Generator)가 외부 AWS 서비스(Kinesis, S3)로 데이터를 초당 수만 건씩 쏘게 되면, 이 트래픽은 모두 NAT Gateway를 타고 인터넷 구간을 거쳐 AWS 백본으로 들어갑니다. 이는 엄청난 NAT Gateway 데이터 처리 비용(Data Processing Charge)을 발생시키며, 보안상으로도 폐쇄망 원칙에 어긋납니다.

개선안 (VPC Endpoint 도입):

network.tf에 S3 Gateway Endpoint와 **Kinesis Interface Endpoint (VPC PrivateLink)**를 반드시 추가하십시오.

데이터 파이프라인 인프라를 설계할 때 대용량 트래픽이 퍼블릭망을 타지 않도록 최적화했다는 점은 데이터 엔지니어 면접에서 매우 강력한 어필 포인트가 됩니다.

4. Flink to SNS Sink의 기술적 난해함 (Phase 3.1)
현재 계획: Flink에서 탐지된 이상 이벤트를 SNS Topic으로 직접 Sink (Publish).

비판: Apache Flink (AWS Managed Flink 포함)는 기본적으로 S3, Kinesis, Kafka 등에 대한 Native Sink 커넥터는 잘 지원하지만, AWS SNS로 직접 쏘는 Native Sink 커넥터는 내장되어 있지 않습니다. 이를 구현하려면 Java/Scala로 커스텀 Async I/O 커넥터를 작성해야 하며, 이는 5/8 데드라인을 심각하게 위협하는 블랙홀이 됩니다.

개선안 (Decoupling):

Flink의 Sink를 SNS가 아닌 **새로운 Alert용 Kinesis Stream(robot-anomaly-alert-stream)**으로 지정하십시오.

해당 Alert Kinesis Stream을 Event Source로 삼아 구동되는 초경량 AWS Lambda 함수를 하나 띄우고, 이 Lambda가 Kinesis 레코드를 읽어 SNS(Slack)로 쏘도록 아키텍처를 분리(Decoupling)하십시오. 이 방식이 AWS 서버리스 스트리밍의 정석입니다.

5. Serving Layer의 쿼리 지연 (Latency) 문제 (Phase 4.3)
현재 계획: FastAPI에서 사용자가 채팅을 칠 때마다 Athena Gold 테이블을 실시간 조회하여 LLM에 컨텍스트로 주입.

비판: Athena는 페타바이트급 데이터를 배치로 분석하는 데 특화된 분산 쿼리 엔진이지, 실시간 API 백엔드용 OLTP 데이터베이스가 아닙니다. 쿼리 시작 시 파티션을 스캔하고 결과를 S3에 쓰는 오버헤드 때문에 간단한 쿼리도 최소 2~5초가 소요됩니다. 사용자 경험(UX) 측면에서 채팅 응답이 극도로 느려집니다.

개선안:

아키텍처상 완벽한 해결책은 Airflow의 마지막 Task에서 Gold 테이블의 결과를 RDS(PostgreSQL)나 DynamoDB로 Export(Reverse ETL)하여 FastAPI가 이를 밀리초(ms) 단위로 읽게 하는 것입니다.

현실적 타협안 (시간 부족 시): FastAPI 내부에 in-memory 캐시(예: 파이썬 cachetools 또는 단순 전역 변수)를 두어, Airflow 배치가 끝나는 매일 자정에 Athena 결과를 한 번만 로드해두고 API 요청은 캐시에서 바로 읽어와 Bedrock으로 넘기도록 수정하십시오.