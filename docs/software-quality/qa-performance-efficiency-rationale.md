# 성능 효율성 점검 항목의 근거

판정용 항목 목록은 [qa-performance-efficiency-guideline.md](./qa-performance-efficiency-guideline.md) 에 있다.
이 문서는 왜 그 기준인지와 예시를 담는다.

주어진 조건에서 사용한 자원 대비 성능을 뜻한다.

하위 특성
* **시간 반응성(time behaviour)**: 응답시간과 처리 시간
* **자원 사용률**: CPU, 메모리, 커넥션, 스레드
* **용량(capacity)**: 감당 가능한 최대 한계

> **수치에는 근거 등급이 표시되어 있다.**
> A는 산술로 도출된 값, B는 출처가 있는 값(링크 표기), C는 근거 없이 정한 예시값이다.
> C로 표시된 값은 그대로 채택하지 말고 측정 후 팀이 확정한다.
> 등급 정의는 quality-attributes.md의 "판정 기준 수치의 성격"을 참고한다.

## 1. 성능은 세 숫자로 정의한다

정성적 표현은 요구사항이 아니다. 다음 세 가지를 숫자로 정해야 설계와 검증이 가능해진다.

| 지표 | 정의 | 주의점 |
|------|------|--------|
| 지연시간(latency) | 요청 하나의 처리 시간 | 평균이 아니라 p95, p99로 본다 |
| 처리량(throughput) | 단위 시간당 처리 건수(TPS, RPS) | 지연시간 조건과 함께 명시한다 |
| 자원 사용률 | CPU, 힙, DB 커넥션 점유율 | 포화 지점을 넘으면 지연이 급증한다 |

평균 응답 50ms인데 p99가 3초면 100명 중 1명은 실패로 체감한다.
평균은 문제를 숨기므로 목표는 항상 백분위수로 정의한다.

점검 항목
* `[설계]` `PERF-1-01` 기능별 지연시간 목표가 백분위수로 정의되어 있는가
* `[설계]` `PERF-1-02` 목표 처리량과 그때의 자원 사용률을 함께 정했는가
* `[프로세스]` `PERF-1-03` 목표를 부하 테스트로 검증했는가

판정 기준 (등급 C. 근거 없음. 서비스 특성에 따라 크게 달라진다)

| 기능 유형 | p50 | p99 | 정한 이유 |
|-----------|-----|-----|------|
| 단순 조회 (단일 행) | 20ms | 100ms | 인덱스 조회 1회 수준 |
| 목록 조회 (집계 포함) | 50ms | 300ms | 조인과 집계 여유 포함 |
| 쓰기 (트랜잭션 1건) | 100ms | 500ms | 트랜잭션과 잠금 포함 |
| 외부 연동 포함 | 300ms | 1.5s | 외부 응답 변동 흡수 |
| 내부 관리 도구, 통계 | 1s | 5s | 사용자 대면이 아님 |

### 용량 산정의 기본

리틀의 법칙 `L = λ * W`가 출발점이다. 이 계산 자체는 등급 A이며, 아래 풀 크기 권장값은 등급 B와 C가 섞여 있다.

* λ = 초당 요청 수, W = 평균 응답시간, L = 동시에 처리 중인 요청 수
* 평균 200ms에 초당 500 요청이면 L은 100이다.
* 톰캣 스레드풀이 50이면 큐가 쌓이고 지연이 지수적으로 증가한다.

스레드풀, DB 커넥션풀, 커넥션 타임아웃은 이 계산으로 함께 정해야 한다.

```yaml
# 개선: 스레드와 커넥션 수를 계산 결과에 맞춰 명시한다
server:
  tomcat:
    threads:
      max: 200                    # 목표 동시 처리 요청 수 + 여유
spring:
  datasource:
    hikari:
      maximum-pool-size: 30       # DB CPU 코어 수 기준. 스레드 수와 같게 잡지 않는다
      minimum-idle: 10
      connection-timeout: 3000
      leak-detection-threshold: 5000   # 5초 이상 반환되지 않는 커넥션을 로그로 드러냄
```

커넥션풀을 스레드 수만큼 크게 잡는 것은 흔한 실수다.
DB가 동시에 효율적으로 처리할 수 있는 수는 코어 수에 가깝고, 그보다 크면 경합만 늘어난다.

커넥션풀 크기의 근거는 HikariCP 위키의 산정식이다 (등급 B).
출처: https://github.com/brettwooldridge/HikariCP/wiki/About-Pool-Sizing

```
connections = (core_count * 2) + effective_spindle_count
```

여기서 `core_count`는 애플리케이션 서버가 아니라 **DB 서버의 물리 코어 수**이고, `effective_spindle_count`는 디스크 수다.
SSD 환경에서는 스핀들 개념이 맞지 않으므로 그대로 적용하기 어렵고, 산정식 자체도 절대값이 아니라 출발점으로 제시된 것이다.
여러 인스턴스가 같은 DB를 공유하면 전체 목표 커넥션 수를 인스턴스 수로 나눈다.

| 항목 | 값 | 등급 |
|------|-----|------|
| 커넥션풀 크기 | `(DB 코어 수 * 2) + 디스크 수`를 인스턴스 수로 나눈 값 | B. 위 출처 |
| HikariCP `maximumPoolSize` 기본값 | 10 | B |
| HikariCP `connectionTimeout` 기본값 | 30000ms | B |
| 커넥션 획득 대기(제안) | 3000ms | C. 기본값 30초는 실패를 늦게 드러낸다는 판단 |
| 커넥션 누수 탐지 | 5000ms | C |
| 커넥션풀 사용률 | 평시 70% 이하 | C |

## 2. DB가 병목의 대부분이다

점검 항목
* `[코드]` `PERF-2-01` 컬렉션 조회 후 루프에서 연관 엔티티에 접근하지 않는가 (N+1)
* `[코드]` `PERF-2-02` 목록 조회에서 건별 집계 쿼리를 반복하지 않는가
* `[설계]` `PERF-2-03` 조회 조건에 맞는 인덱스가 있고 실제로 타는가
* `[프로세스]` `PERF-2-04` 슬로우 쿼리를 정기적으로 확인하는가

판정 기준 (등급 C. 근거 없음)

| 항목 | 기준 | 조치 |
|------|------|------|
| 요청당 쿼리 수 | 10개 이하 | 20개 초과 시 N+1 의심 |
| 단일 쿼리 실행 시간 | 100ms 이하 | 1초 초과는 슬로우 쿼리 |
| 스캔 행 수 / 반환 행 수 | 100배 이하 | 초과 시 인덱스 부적합 |
| 테이블당 인덱스 수 | 5개 이하 | 초과 시 쓰기 비용 검토 |

```java
// 점검 대상: 목록 조회 1회 + 항목마다 연관 엔티티 조회 N회
List<Record> records = recordRepository.findAll();
records.forEach(r -> r.getOwner().getName());

// 개선: fetch join으로 한 번에
@Query("SELECT r FROM Record r JOIN FETCH r.owner")
List<Record> findAllWithOwner();
```

집계가 필요하면 건별 쿼리 대신 한 번에 모아 애플리케이션에서 매핑한다.

```sql
-- 개선: 목록에 필요한 집계를 한 방에 처리 (건별 쿼리 N회 대신 1회)
SELECT resource_id, SUM(remaining_qty) AS available_qty
FROM resource_allocation
WHERE resource_id IN (?, ?, ...)
  AND status = 'ACTIVE'
  AND expires_at >= ?
GROUP BY resource_id;
```

## 3. MySQL 8.4 인덱스 원칙

* **왼쪽 접두어 규칙**: `(a, b, c)` 인덱스는 `WHERE b = ?` 단독 조회에 쓰이지 않는다.
* **함수 적용 금지**: 인덱스 컬럼을 함수로 감싸면 인덱스를 못 탄다.
* **커버링 인덱스**: 조회에 필요한 컬럼을 인덱스에 포함시키면 테이블 접근이 0이 된다.
* **선행 와일드카드 금지**: `LIKE '%kim'`은 인덱스를 무력화한다.
* **카디널리티**: 값 종류가 적은 컬럼(status 등) 단독 인덱스는 효과가 낮다. 선택도 높은 컬럼과 조합한다.

```sql
-- 점검 대상: created_at에 함수를 씌워 인덱스 활용 불가
SELECT * FROM record WHERE DATE(created_at) = '2026-07-29';

-- 개선: 범위 조건
SELECT * FROM record
WHERE created_at >= '2026-07-29 00:00:00'
  AND created_at <  '2026-07-30 00:00:00';
```

```sql
-- 커버링 인덱스 예: 조회와 집계에 쓰는 컬럼까지 포함해 테이블 접근 제거
-- 앞쪽은 등호 조건, 그다음 범위 조건, 마지막에 집계 대상 컬럼
KEY idx_alloc_cover (resource_id, status, expires_at, remaining_qty)
```

검증은 추측이 아니라 실행 계획으로 한다.

```sql
EXPLAIN ANALYZE
SELECT resource_id, SUM(remaining_qty)
FROM resource_allocation
WHERE resource_id IN (1, 2, 3) AND status = 'ACTIVE'
GROUP BY resource_id;
```

확인할 것은 `type`이 `ALL`(풀 스캔)이 아닌지, `key`에 의도한 인덱스가 잡혔는지, `rows` 추정치가 과도하지 않은지다.

### 슬로우 쿼리 상시 수집

MySQL의 `long_query_time` 기본값은 10초이고, `slow_query_log`는 기본 비활성이다 (등급 B).
아래 1초는 개선 대상을 더 넓게 잡기 위해 낮춘 값이며 등급 C다.

```sql
-- 개선: 1초 이상 걸린 쿼리와 인덱스를 못 탄 쿼리를 함께 남긴다
SET GLOBAL slow_query_log = 'ON';
SET GLOBAL long_query_time = 1;
SET GLOBAL log_queries_not_using_indexes = 'ON';
SET GLOBAL log_throttle_queries_not_using_indexes = 60;   -- 분당 60건으로 제한
```

```sql
-- 개선: 누적 실행 시간이 큰 쿼리를 상위부터 확인한다
SELECT DIGEST_TEXT,
       COUNT_STAR,
       ROUND(SUM_TIMER_WAIT / 1000000000000, 2) AS total_sec,
       ROUND(AVG_TIMER_WAIT / 1000000000, 2)    AS avg_ms,
       SUM_ROWS_EXAMINED / NULLIF(SUM_ROWS_SENT, 0) AS scan_ratio
FROM performance_schema.events_statements_summary_by_digest
ORDER BY SUM_TIMER_WAIT DESC
LIMIT 20;
```

평균이 빠른 쿼리라도 호출 횟수가 많으면 누적 부하는 크다.
개선 대상은 평균이 아니라 누적 실행 시간 순으로 고른다.

## 4. 애플리케이션 레벨

점검 항목
* `[코드]` `PERF-4-01` 반복문 안에서 반복마다 같은 연산을 다시 하지 않는가
* `[코드]` `PERF-4-02` 조회 패턴에 맞는 자료구조를 쓰는가
* `[코드]` `PERF-4-03` 대용량 처리에서 전체를 메모리에 올리지 않는가
* `[인프라]` `PERF-4-04` 힙 크기와 GC 설정이 데이터 규모에 맞는가

```java
// 점검 대상: 항목 N개마다 사용자 M개 전체 순회 -> O(N*M)
for (Record record : records) {
    User user = users.stream()
        .filter(u -> u.getId().equals(record.getUserId()))
        .findFirst().orElseThrow();
}

// 개선: 한 번 인덱싱 후 O(1) 조회
Map<Long, User> userMap = users.stream()
    .collect(Collectors.toMap(User::getId, Function.identity()));
for (Record record : records) {
    User user = userMap.get(record.getUserId());
}
```

```java
// 점검 대상: 백만 건을 한 번에 메모리로 -> OutOfMemoryError
List<Record> all = recordRepository.findAll();

// 개선: 청크 단위로 처리하고 영속성 컨텍스트를 비운다
int page = 0;
Page<Record> chunk;
do {
    chunk = recordRepository.findAll(PageRequest.of(page++, 1000));
    chunk.forEach(this::process);
    entityManager.clear();
} while (chunk.hasNext());
```

판정 기준 (등급 C. 근거 없음)

| 항목 | 기준 |
|------|------|
| 배치 청크 크기 | 1000행 |
| 한 번에 메모리에 올리는 행 수 | 10000행 이하 |
| GC 일시정지 p99 | 200ms 이하 |
| 힙 사용률 (GC 직후) | 70% 이하 |

## 5. 캐시는 마지막 수단이다

캐시는 성능을 사고 정합성을 판다. 병목이 실제로 측정된 뒤에 도입한다.

점검 항목
* `[프로세스]` `PERF-5-01` 캐시 도입 전에 쿼리와 인덱스 개선을 먼저 시도했는가
* `[설계]` `PERF-5-02` 무효화 시점이 명확한가
* `[코드]` `PERF-5-03` 캐시 미스 폭주(cache stampede)에 대비했는가
* `[코드]` `PERF-5-04` 캐시가 죽어도 서비스가 동작하는가

판정 기준 (등급 C. 근거 없음)

| 항목 | 기준 | 근거 |
|------|------|------|
| 도입 조건 | 동일 조회 반복률 70% 이상 | 그 이하는 효과가 작다 |
| 적중률 목표 | 90% 이상 | 미달 시 키 설계 재검토 |
| TTL | 근사 허용 시간에 맞춘다 | 자주 바뀌는 집계 30초, 거의 안 바뀌는 기준 정보 10분 |
| TTL 지터 | TTL의 10% | 동시 만료로 인한 폭주 방지 |
| 캐시 장애 시 | 원본 조회로 통과(fail open) | 단 원본 부하 상한 필요 |

```java
// 점검 대상: 만료 순간 동일 키 요청이 전부 DB로 몰린다 (stampede)
public Resource get(Long id) {
    Resource cached = cache.get(id);
    if (cached == null) {
        cached = resourceRepository.findById(id).orElseThrow();
        cache.put(id, cached);
    }
    return cached;
}

// 개선: 키 단위로 재생성을 한 번만 수행하고 나머지는 그 결과를 공유한다
public Resource get(Long id) {
    return cache.get(id, key -> resourceRepository.findById(key).orElseThrow());
}
```

정확성이 필요한 경로와 근사가 허용되는 경로를 분리하는 것이 핵심이다.
같은 수치라도 목록에 표시할 때는 몇 초 낡아도 문제가 없지만, 그 수치를 근거로 자원을 차감하는 시점에는 정확해야 한다.
전자는 캐시, 후자는 실시간 조회와 잠금으로 처리한다.

## 6. 성능 검증 절차

점검 항목
* `[프로세스]` `PERF-6-01` 주요 릴리스 전에 부하 테스트를 수행하는가
* `[프로세스]` `PERF-6-02` 운영과 유사한 데이터 규모에서 검증하는가
* `[프로세스]` `PERF-6-03` 한계점(포화 지점)을 알고 있는가

```
부하 테스트 절차

1. 데이터 준비: 운영의 최소 50% 규모. 행 수가 적으면 인덱스 문제가 드러나지 않는다
2. 기준선 측정: 현재 목표 트래픽에서 p50, p99, 자원 사용률
3. 단계 증가: 목표의 50%, 100%, 150%, 200%로 5분씩
4. 포화 지점 기록: 응답시간이 급격히 꺾이는 지점의 RPS
5. 판정
   - 목표 트래픽에서 p99 목표 충족
   - 포화 지점이 목표 트래픽의 2배 이상
   - 포화 시 오류가 아니라 거절로 처리되는지 확인
6. 결과와 병목 구간 기록. 다음 회차와 비교
```

데이터가 적은 환경의 부하 테스트는 통과해도 의미가 없다.
1000행에서는 풀 스캔도 빠르다.

## 7. 측정 지표

| 지표 | 수집 방법 | 경보 기준 (예시값) |
|------|-----------|--------------------|
| API p50, p95, p99 지연시간 | Micrometer, APM | 기능별 목표 초과 |
| 처리량(RPS) | 게이트웨이 또는 애플리케이션 메트릭 | 포화 지점의 70% 도달 |
| DB 커넥션 풀 사용률과 대기 시간 | HikariCP 메트릭 | 사용률 85% 초과 |
| slow query 발생 건수 | slow query log, `performance_schema` | 시간당 10건 초과 |
| GC 일시정지 시간과 빈도 | JVM GC 로그 | p99 200ms 초과 |
| 부하 한계점 | k6, Gatling 등 부하 테스트 | 목표의 2배 미만 |

측정 없이 하는 최적화는 유지보수성만 잃고 성능은 얻지 못한다.
프로파일링으로 병목 구간을 특정한 뒤에 손댄다.

## 8. 관련 문서

* 확장 전략: [qa-flexibility-rationale.md](./qa-flexibility-rationale.md)
* 캐시와 정합성의 충돌: [qa-tradeoffs-rationale.md](./qa-tradeoffs-rationale.md)
* 측정 기반 판단: [qa-observability-rationale.md](./qa-observability-rationale.md)

## 9. 참고 문헌

| 항목 | 링크 |
|------|------|
| HikariCP, About Pool Sizing (커넥션풀 산정식) | https://github.com/brettwooldridge/HikariCP/wiki/About-Pool-Sizing |
| MySQL 8.4 Reference Manual, 서버 시스템 변수 | https://dev.mysql.com/doc/refman/8.4/en/server-system-variables.html |
| MySQL 8.4 Reference Manual, InnoDB 시스템 변수 | https://dev.mysql.com/doc/refman/8.4/en/innodb-parameters.html |
