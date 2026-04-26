# UI Design Guide: Robot Fleet Control System

## 1. 디자인 원칙
1. **Tool-First:** 마케팅 페이지가 아닌 산업용 제어판이다. 심미성보다 기능성이 우선한다.
2. **Signal over Noise:** 수천 개의 데이터 중 Anomaly(이상 징후)만 즉각적으로 눈에 띄어야 한다.
3. **Tabular Data Efficiency:** 수치 데이터는 가독성과 정렬을 위해 고정폭(Monospace)을 사용한다.
4. **Exception-First:** 정상 상태보다 '문제 상태'가 설계의 최상단에 위치하며, 운영자의 개입이 필요한 정보를 우선한다.

## 2. AI 슬롭 안티패턴 (절대 금지)
| 금지 사항 | 이유 |
|-----------|------|
| Glassmorphism / Blur | 시스템 리소스 낭비 및 실시간 데이터 시인성 저하 |
| 차트 애니메이션 | 수치 변화 시 차트가 움직이면 정확한 모니터링 방해 |
| 보라/인디고 브랜드 컬러 | 산업용 관제 시스템의 신뢰도와 거리감 있음 |
| Rounded-2xl (과한 둥글기) | 공간 낭비가 심함. 각진 형태(rounded-sm/md) 권장 |

## 3. 색상 및 시맨틱 상태 (Dark Mode Only)
### 3.1 배경 및 카드
- **Page:** `#0a0a0a`
- **Card:** `#111111`
- **Border:** `#262626`

### 3.2 다중 인코딩 상태 (Color + Shape)
*적록색약 및 고대비 환경을 위해 색상과 아이콘/형태를 반드시 병행 표기한다.*
- **Critical (Error):** `#ef4444` | 아이콘: `🛑 (Octagon/X)`
- **Warning (Alert):** `#f59e0b` | 아이콘: `⚠️ (Triangle/!)`
- **Normal (Success):** `#22c55e` | 아이콘: `✅ (Circle/Check)`
- **Offline (Neutral):** `#525252` | 아이콘: `⚪ (Gray Circle)`

## 4. 알림 생명주기 (Alert Lifecycle)
- **Unacknowledged (미확인):** 신규 Critical 에러 발생 시, 작업자가 '확인(Ack)' 버튼을 누르기 전까지 카드 테두리가 1초 간격으로 무한 점멸(Blinking)한다.
- **Acknowledged (확인됨):** 확인된 에러는 점멸을 멈추고 고정된 시맨틱 색상만 유지하여 시각적 피로도를 줄인다.

## 5. 데이터 정렬 및 타이포그래피
- **수치 데이터:** `font-mono tabular-nums`. 모든 숫자 데이터는 **우측 정렬(Right-aligned)**하여 자릿수 비교 및 수직 스캐닝 효율을 최적화한다.
- **텍스트 라벨:** 로봇 ID, 상태 메시지 등은 **좌측 정렬(Left-aligned)**한다.

## 6. 레이아웃 및 정보 밀도
- **Exception-First Sorting:** `Critical` > `Warning` > `Normal` 순으로 자동 정렬한다. 장애 로봇이 항상 최상단 첫 번째 그리드에 위치해야 한다.
- **Summary View:** 정상 상태의 로봇은 개별 카드를 나열하지 않고 "🟢 95대 정상 가동 중"과 같은 요약 텍스트로 축소하여 정보 밀도를 관리한다.
- **Grid System:** 12컬럼 시스템을 사용하며, 요소 간 간격은 `gap-2`를 유지하여 화면 공간을 극대화한다.

## 7. 인터랙션 및 물리적 제약 (Physical Context)
- **Touch Targets:** 현장 터치스크린 및 장갑 착용 환경을 고려하여 모든 버튼은 최소 **44x44px** 이상의 클릭 영역을 확보한다.
- **Primary Action:** `rounded-sm bg-neutral-100 text-black hover:bg-white px-3 py-2 text-sm font-bold`

## 8. 애니메이션 가이드
- **허용:** 미확인 에러의 지속적 점멸(Attention), 신규 데이터 로드 시 `fade-in`.
- **금지:** 슬라이딩, 메뉴 펼침 애니메이션, 차트 드로잉 효과 등 시스템 반응 속도를 저하시키는 모든 전환 효과.