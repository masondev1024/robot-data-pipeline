# Seed Data

Generator가 로봇 시뮬레이션의 기준값(프로필)으로 사용하는 데이터 디렉토리입니다.

## 파일 구성

| 파일 | 크기 | 용도 | git |
|------|------|------|-----|
| `seed_data_sample.csv` | ~200행 | 로컬 개발·CI 테스트용 합성 데이터 | ✅ 커밋 |
| `seed_data.csv` | ~10,000행 | 운영 배포용 Kaggle 전체 데이터 | ❌ gitignore |
| `generate_sample.py` | — | sample CSV 생성 스크립트 | ✅ 커밋 |

## 데이터셋 출처

**AI4I 2020 Predictive Maintenance Dataset**
- URL: https://www.kaggle.com/datasets/stephanmatzka/predictive-maintenance-dataset-ai4i-2020
- 라이선스: CC BY 4.0
- 컬럼: `Air temperature [K]`, `Process temperature [K]`, `Rotational speed [rpm]`, `Torque [Nm]`, `Tool wear [min]`, `Machine failure`

## 운영 배포 시 준비 방법

```bash
# 1. Kaggle CLI 설치
pip install kaggle

# 2. Kaggle API 키 설정 (~/.kaggle/kaggle.json)
kaggle datasets download stephanmatzka/predictive-maintenance-dataset-ai4i-2020

# 3. 압축 해제 후 이 디렉토리에 배치
unzip predictive-maintenance-dataset-ai4i-2020.zip -d data/
mv data/ai4i2020.csv data/seed_data.csv

# 4. .env에서 경로 변경
# SEED_CSV_PATH=data/seed_data.csv
```

## 컬럼 매핑 (Generator → Robot Telemetry)

| Kaggle 컬럼 | 로봇 텔레메트리 필드 | 변환 방식 |
|-------------|-------------------|----------|
| `Process temperature [K]` | `motor_temp` 베이스 | K-273.15, 60~100°C 클램프 |
| `Rotational speed [rpm]` | `current_load` 베이스 | 1168~2886 rpm → 0~100 정규화 |
| `Tool wear [min]` | `drain_factor` | 0~250 → 0.1~3.0 |
| `Machine failure` = 1 | `motor_temp` 스파이크 확률 | 5% 확률로 91~99°C 스파이크 |
| — (생성) | `pos_x`, `pos_y` | 공장 그리드 균등 배치 |
| — (생성) | `battery_level` | drain_factor 기반 점진 감소 |
