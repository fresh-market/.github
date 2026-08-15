# 미결정 값

이 디렉터리의 판정 기준 수치 중 **아직 근거가 없는 것**을 모은다.

각 문서는 임계치에 등급을 붙여 둔다.

| 등급 | 뜻 |
|------|-----|
| A | 산술로 도출된 값 |
| B | 출처가 있는 값 |
| C | **근거 없이 정한 예시값** |

등급 C는 "적당히"라고 두면 판정이 사람마다 달라지므로 구체적인 숫자를 적어 둔 것일 뿐,
검증된 권장값이 아니다. 이 문서는 그중 아직 채워지지 않은 것을 추린다.

`fresh-market/fm-infra`의 미결정 값은 그쪽 [pending-decisions.md](https://github.com/fresh-market/fm-infra/blob/main/docs/infra-review/pending-decisions.md)에 있다.
`fresh-market/fm-backend`에는 미결정 값이 없다. 코드 관용과 패턴을 다루므로 임계치가 없기 때문이다.

---

## 1. 확정값이 이미 채운 것

**이 문서들을 고칠 필요는 없다.** 등급 C로 두되, 게이트는 `fresh-market/fm-infra`의 확정값으로 판정한다.
두 층이 다르게 말하면 확정값이 이긴다. 근거가 더 구체적이기 때문이다.

| 여기의 예시값 | 위치 | 확정값 |
|---------------|------|--------|
| 가용성 목표 99.5~99.95% | `qa-reliability-rationale.md` 39행 | 장애 시나리오 9종별 RTO와 RPO, 보장 메커니즘까지 |
| 타임아웃 예산 (게이트웨이 10s, 서비스 간 1s/5s) | `qa-reliability-rationale.md` 68행 | 종료 4계층(30/30/45/60초), 요청 4계층(3/5/10/60초) |
| RPO와 RTO 등급표 | `qa-reliability-rationale.md` 325행 | 시나리오별 실제 값 |
| graceful shutdown 30초, readiness 연속 3회 | `qa-reliability-rationale.md` 381행 | 확정. 경로와 임계값까지 |
| 추적 샘플링 (오류 100%, 핵심 10%) | `qa-observability-rationale.md` 198행 | 평상시 10%, 부하 시험 5%, 장애 주입 100%, 오류 100% |
| 커넥션풀 산식 | 여러 곳 | `maximum-pool-size: 10`, `minimum-idle: 10` |

**확정값이 더 엄격한 경우도 있다.** 복원 리허설은 여기가 "분기 1회 이상"인데 확정값은 **주 1회**이고,
테스트 커버리지는 여기가 "목표로 삼지 않는다"인데 확정값은 **service 패키지 메서드 100%, 미달 시 병합 차단**이다.
확정값 층이 빈칸을 메우는 것이 아니라 판정 기준을 실제로 대체한다는 뜻이다.

---

## 2. 측정해야 정해지는 것

**읽어서 정할 수 없다.** 실제 트래픽이나 데이터를 봐야 한다.
그전까지 이 값에 걸린 항목은 근거 판정(기록이 있는가)만 가능하고 일치 판정(값이 같은가)은 불가능하다.

| 값 | 위치 | 현재 예시값 | 무엇을 재야 하는가 |
|------|------|-------------|--------------------|
| 기능별 지연시간 목표 | `qa-performance-efficiency-rationale.md` 33행 | 단순 조회 p99 100ms, 목록 300ms, 쓰기 500ms | 부하 시험에서 실제 분포 |
| 요청당 쿼리 수 | `qa-performance-efficiency-rationale.md` 99행 | 10개 이하, 20개 초과 시 N+1 의심 | 실제 화면별 쿼리 수 |
| 배치 청크 크기 | `qa-performance-efficiency-rationale.md` 232행 | 1000행, 메모리 상한 10000행 | 힙 크기와 행 크기 |
| 캐시 도입 조건 | `qa-performance-efficiency-rationale.md` 251행 | 반복률 70% 이상, 적중률 90% | 실제 조회 패턴 |
| 낙관적 잠금 선택 기준 | `qa-data-integrity-rationale.md` 40행 | 충돌률 1% 미만 | **실제 충돌률.** 문서가 스스로 "측정한 뒤 확정한다"고 적었다 |
| 트랜잭션 지속 시간 | `qa-data-integrity-rationale.md` 175행 | 100ms 이하, 상한 1초 | 실제 트랜잭션 분포 |
| 아웃박스 지연과 적체 | `qa-data-integrity-rationale.md` 248행 | 5초 이내, 100건 초과 시 경보 | 발행 처리량 |
| 락 유지 시간 | `qa-flexibility-rationale.md` 119행 | 예상 작업 시간의 3배, 최대 30분 | 배치 최대 실행 시간 |
| 요청 대기 큐 | `qa-reliability-rationale.md` 259행 | 스레드풀의 2배, 대기 1초 | 톰캣 스레드 수 실측 |
| 로그량 | `qa-observability-rationale.md` 46행 | 요청당 INFO 3줄, 단일 로그 2KB | 실제 로그 볼륨과 비용 |
| 메트릭 카디널리티 | `qa-observability-rationale.md` 139행 | 시계열 1000개, 태그 값 50개 | 실제 태그 조합 |
| 레이트 리밋 | `qa-security-rationale.md` 304행 | 계정당 5회/15분, IP당 30회/15분 | **실제 사용 패턴.** 문서가 "관측한 뒤 확정한다"고 적었다 |
| 단위 테스트 실행 시간 | `qa-maintainability-rationale.md` 103행 | 전체 1분, 단일 100ms | 테스트가 쌓인 뒤 |

**`qa-data-integrity-rationale.md` 40행과 `qa-security-rationale.md` 304행은 문서가 스스로 미확정이라고 밝혔다.** 나머지보다 우선한다.

---

## 3. 팀이 고르면 되는 것

**측정이 필요 없다.** 지금 정할 수 있고, 정하면 등급 C에서 벗어난다.

| 값 | 위치 | 현재 예시값 | 무엇을 보고 정하는가 |
|------|------|-------------|----------------------|
| 폐기 예고 기간 | `qa-compatibility-rationale.md` 48~52행 | 30일, 180일 | **클라이언트 업데이트 주기.** 문서가 "확인한 뒤 팀이 정해야 한다"고 적었다 |
| 페이지 크기 | `qa-compatibility-rationale.md` 118행 | 기본 20, 최대 100 | 화면 설계 |
| 온라인 DDL 필수 대상 | `qa-compatibility-rationale.md` 188행 | 행 수 100만 이상 | 실제 테이블 크기 |
| 배치 전용 커넥션 비율 | `qa-compatibility-rationale.md` 207행 | 최대 커넥션의 20% 이하 | 커넥션 풀 확정값과 함께 |
| 필드 명명 규칙 | `qa-compatibility-rationale.md` 250행 | snake_case 또는 camelCase 중 하나 | **택일이다.** 혼용만 아니면 된다 |
| 금액 표현과 반올림 | `qa-functional-suitability-rationale.md` 149행 | `DECIMAL(19,4)`, `HALF_UP` | 도메인 정책 |
| 외부 호출 실패 분기 | `qa-functional-suitability-rationale.md` 59행 | 최소 3가지 | 연동 대상 수 |
| 심각도 등급 정의 | `qa-incident-response-rationale.md` 24행 | SEV1~SEV4 | **서비스 규모.** 문서가 "재정의한다"고 적었다 |
| 안정화 관찰 시간 | `qa-incident-response-rationale.md` 85행 | 최소 30분 | 운영 경험 |
| 훈련 주기 | `qa-incident-response-rationale.md` 379행 | 유형별 | 팀 여력 |
| 중복 코드 비율 | `qa-maintainability-rationale.md` 150행 | 5% 이하, 정책 변경 파일 3개 이하 | SonarQube 기본값 사용 여부 |
| 요청 본문과 업로드 상한 | `qa-security-rationale.md` 152행 | 1MB, 10MB | 업로드 기능 유무 |
| 해시 파라미터 재검토 주기 | `qa-security-rationale.md` 221행 | 미정 | 팀 규율 |

**`qa-compatibility-rationale.md` 250행은 택일이라 가장 쉽다.** snake_case 든 camelCase 든 하나로 통일만 하면 되고,
정하지 않으면 `CMP-7-01`(명명 일관성)을 판정할 기준이 없다.

---

## 4. 등급 C로 남겨도 되는 것

전부 채울 필요는 없다. 아래는 값이 아니라 **판단 절차**라서 숫자로 확정할 대상이 아니다.

| 위치 | 내용 |
|------|------|
| `qa-flexibility-rationale.md` 73행 | 무상태 확인 방법 (인스턴스를 죽여 보기) |
| `qa-flexibility-rationale.md` 186행 | 추상화가 필요한 상황 |
| `qa-data-integrity-rationale.md` 153행 | 규칙 유형별 DB 제약 매핑 |
| `qa-maintainability-rationale.md` 72행 | 순환 참조 0건 |
| `qa-incident-response-rationale.md` 240, 288행 | 확인 순서, 런북 구성 |

`0건`처럼 자명한 것도 등급 C로 표기되어 있는데, 이것은 근거가 없어서가 아니라 표기를 일괄 적용한 결과다.

---

## 다음에 할 일

| 순위 | 무엇 | 드는 시간 |
|------|------|-----------|
| 1 | 필드 명명 규칙 택일 (`qa-compatibility-rationale.md` 250행) | 결정 하나 |
| 2 | 심각도 등급 정의 (`qa-incident-response-rationale.md` 24행) | 회의 30분 |
| 3 | 폐기 예고 기간 (`qa-compatibility-rationale.md` 48행) | 클라이언트 정책 확인 후 |
| 4 | 금액 표현과 반올림 (`qa-functional-suitability-rationale.md` 149행) | 도메인 확정 후 |
| 5 | 나머지 3장 항목 | 필요할 때 |
| 6 | 2장 전체 | 부하 시험 이후 |

**3장(팀이 고르면 되는 것)이 먼저다.** 측정 없이 정할 수 있는데 안 정해 두면,
게이트가 근거 없는 예시값으로 판정하거나 판정을 포기한다.

## 관련 문서

* 등급 정의와 층위: [quality-attributes.md](./quality-attributes.md)
* 게이트 설계: [qa-llm-verification.md](./qa-llm-verification.md) 7.2절
* 확정값 쪽 미결정: `fresh-market/fm-infra`의 `docs/infra-review/pending-decisions.md`
* 문서 간 모순 목록(기계 판독): `.github/llm-verify/known-conflicts.yml`
