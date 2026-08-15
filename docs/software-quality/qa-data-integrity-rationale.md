# 데이터 정합성 점검 항목의 근거

판정용 항목 목록은 [qa-data-integrity-guideline.md](./qa-data-integrity-guideline.md) 에 있다.
이 문서는 왜 그 기준인지와 예시를 담는다.

데이터가 언제나 업무 규칙에 부합하는 상태로 유지되는 정도를 뜻한다.

ISO/IEC 25010:2023에서 독립 특성은 아니며, 보안의 무결성(integrity)과 신뢰성의 무결함성에 걸쳐 있다.
그러나 백엔드에서는 서비스 종류를 가리지 않고 발생하며 원인이 뚜렷하므로 별도로 다룬다.
한정 수량이 음수가 되거나 같은 요청이 두 번 처리되는 문제는 성능 저하와 달리 되돌리기 어렵다.

이 문서에서 "한정 자원"은 동시에 여러 요청이 줄여 나가는 유한한 수량을 뜻한다.
재고, 좌석, 쿠폰 발급 수, API 크레딧, 계좌 잔액이 모두 같은 구조다.
예시 코드는 `resource_allocation` 테이블의 `remaining_qty`로 표기한다.

> **수치에는 근거 등급이 표시되어 있다.**
> A는 산술로 도출된 값, B는 출처가 있는 값(링크 표기), C는 근거 없이 정한 예시값이다.
> C로 표시된 값은 그대로 채택하지 말고 측정 후 팀이 확정한다.
> 등급 정의는 quality-attributes.md의 "판정 기준 수치의 성격"을 참고한다.

## 1. 갱신 손실 (lost update)

조회한 뒤 수정하는 흐름에서, 두 요청이 같은 값을 읽고 각자 바꿔 저장하면 나중 저장이 앞선 저장을 덮어쓴다.

```java
// 잔여 10에서 두 요청이 동시에 1씩 차감하면 결과가 8이 아니라 9가 된다
Allocation alloc = allocationRepository.findById(id).orElseThrow(); // 둘 다 10을 읽음
alloc.setRemainingQty(alloc.getRemainingQty() - 1);                 // 둘 다 9를 계산
allocationRepository.save(alloc);                                   // 나중 저장이 앞을 덮어씀
```

한정 자원의 차감이나 잔액 변경처럼 정합성이 중요한 데이터에서 이 손실이 발생하면 직접적인 사고로 이어진다.
평소에는 드물게 나타나다가 트래픽이 몰리는 구간에서 한꺼번에 터진다.

## 2. 잠금 전략 선택

점검 항목
* `[코드]` `DI-2-01` 갱신 손실 가능성이 있는 흐름에 잠금을 적용했는가
* `[설계]` `DI-2-02` 충돌 빈도에 맞는 잠금 방식을 골랐는가
* `[코드]` `DI-2-03` 잠금 획득 순서가 일정해 교착 상태(deadlock)를 유발하지 않는가
* `[코드]` `DI-2-04` 낙관적 잠금 실패 시의 처리(재시도 또는 안내)가 정의되어 있는가

판정 기준 (등급 C. 근거 없음. 실제 충돌률을 측정한 뒤 확정한다)

| 충돌률 | 권장 방식 | 정한 이유 |
|--------|-----------|------|
| 1% 미만 | 낙관적 잠금 | 실패가 드물어 재시도 비용이 낮다 |
| 1~10% | 낙관적 잠금 + 재시도 3회 | 재시도로 대부분 흡수된다 |
| 10% 초과 | 비관적 잠금 또는 원자적 갱신 | 재시도가 오히려 부하를 키운다 |
| 단일 행 집중 | 원자적 UPDATE 또는 큐 직렬화 | 특정 자원 하나에 요청이 몰리는 경우 |

충돌률은 낙관적 잠금 예외 발생 건수를 전체 갱신 시도로 나눈 값으로 측정한다.
측정 없이 방식을 고르면 근거가 없다.

### 낙관적 잠금

충돌이 드물다고 보고, 저장 시점에 버전이 그사이 바뀌었는지 확인해 충돌이면 실패시킨다.

```java
@Entity
public class Allocation {
    @Version
    private Long version;   // 저장 시 버전이 다르면 예외를 던져 갱신 손실을 막는다
}
```

실패했을 때의 처리를 반드시 함께 설계해야 한다.
예외만 던지고 끝내면 사용자에게는 이유 없는 실패로 보인다.

```java
// 개선: 짧은 재시도로 흡수하고, 그래도 실패하면 명확한 안내로 변환한다
@Retryable(
    retryFor = ObjectOptimisticLockingFailureException.class,
    maxAttempts = 3,
    backoff = @Backoff(delay = 50, multiplier = 2, random = true)
)
public void decrease(Long allocationId, int quantity) { ... }

@Recover
public void recover(ObjectOptimisticLockingFailureException e, Long allocationId, int quantity) {
    throw new AllocationConflictException("요청이 몰리고 있습니다. 잠시 후 다시 시도해 주세요.");
}
```

### 비관적 잠금

처음부터 행을 잠가 다른 트랜잭션의 접근을 막는다. 충돌이 잦을 때 유리하다.

```java
@Lock(LockModeType.PESSIMISTIC_WRITE)
@Query("SELECT a FROM Allocation a WHERE a.id = :id")
Optional<Allocation> findByIdForUpdate(@Param("id") Long id);
```

```sql
-- MySQL 8.4: 대기 없이 즉시 실패시키거나, 잠긴 행을 건너뛸 수 있다
SELECT * FROM resource_allocation WHERE resource_id = ? FOR UPDATE NOWAIT;
SELECT * FROM job_queue WHERE status = 'READY' LIMIT 10 FOR UPDATE SKIP LOCKED;
```

`SKIP LOCKED`는 큐 소비처럼 여러 워커가 겹치지 않게 작업을 가져갈 때 유용하다.

잠금 대기 상한도 설정으로 정한다.

```sql
-- 개선: 무한 대기 대신 상한을 둔다 (기본 50초는 대부분의 API에 너무 길다)
SET GLOBAL innodb_lock_wait_timeout = 5;
```

| 항목 | 값 | 등급 |
|------|-----|------|
| `innodb_lock_wait_timeout` 기본값 | 50초 | B. MySQL 8.4 매뉴얼 |
| `innodb_lock_wait_timeout` 제안값 | 5초 | C. API 응답 예산 안에서 실패를 드러내려는 판단 |
| 잠금 보유 시간 | 100ms 이하 | C |
| 교착 발생 | 일 1건 초과 시 조사 | C |

MySQL 매뉴얼은 잠금 대기 시간이 초과되면 트랜잭션 전체가 아니라 **실행 중이던 문장만** 롤백된다고 명시한다.
전체를 롤백하려면 `--innodb-rollback-on-timeout`을 켜야 한다.
또한 매뉴얼은 교착과 잠금 대기 시간 초과가 바쁜 서버에서는 정상적으로 발생하는 현상이므로 애플리케이션이 재시도로 대응해야 한다고 설명한다.
따라서 "교착 0건"을 목표로 삼는 것은 적절하지 않고, 발생 빈도의 추세를 보는 편이 맞다.
출처: https://dev.mysql.com/doc/refman/8.4/en/innodb-parameters.html

### 원자적 갱신

읽고 계산해서 쓰는 대신 DB에서 한 번에 갱신하면 잠금 없이도 손실을 막을 수 있다.

```sql
-- 개선: 조건과 갱신을 한 문장으로 -> 영향 행 수가 0이면 잔여 부족
UPDATE resource_allocation
SET remaining_qty = remaining_qty - ?
WHERE id = ? AND remaining_qty >= ?;
```

영향받은 행 수를 반드시 확인해야 한다. 0이면 실패로 처리한다.

## 3. 애플리케이션 로직만 믿지 않는다

버그, 배치, 수동 SQL은 애플리케이션 검증을 우회한다. DB 제약이 최종 방어선이다.

점검 항목
* `[설계]` `DI-3-01` 유일성이 필요한 값에 UNIQUE 제약이 있는가
* `[설계]` `DI-3-02` 값 범위 규칙이 CHECK 제약으로도 표현되어 있는가
* `[설계]` `DI-3-03` 참조 무결성이 필요한 곳에 외래 키가 있는가
* `[설계]` `DI-3-04` NOT NULL이 필요한 컬럼에 지정되어 있는가
* `[코드]` `DI-3-05` 두 외래 키가 같은 조상을 가리켜야 한다면 그 조합을 검증하는가
  참조가 둘 이상이면 각각의 외래 키가 유효해도 조합이 틀릴 수 있다.
  리뷰가 A 상품을 가리키는데 그 근거인 주문 상품은 B 상품인 경우가 그렇고, 두 외래 키는 모두 통과한다.
  한 테이블 안의 값이 아니라 조상까지 올라가 비교해야 하는 조건이라 CHECK로 표현할 수 없다.
  요청 경로에 있는 식별자로 조상을 다시 조회해 대조하고, 어긋나면 거부한다.
* `[코드]` `DI-3-06` 자식 행 합계가 부모의 상한을 넘지 않도록 잠그고 검사하는가
  행 하나씩은 유효한데 합계가 넘는 경우다. 3개 주문한 것을 2개짜리 반품 두 건으로 나누면 각 행은 정상이다.
  읽고 더한 뒤 쓰는 사이에 다른 트랜잭션이 끼면 `DI-2-01`(갱신 손실)과 같은 형태가 되므로 잠금이 함께 필요하다.
  부모에 소진 카운터를 두면 조건부 UPDATE 한 번으로 끝나고, 없으면 부모 행을 잠그고 합계를 다시 센다.

```sql
ALTER TABLE resource_allocation
    ADD CONSTRAINT chk_remaining_qty CHECK (remaining_qty >= 0);

ALTER TABLE external_request
    ADD CONSTRAINT uk_external_request_idem UNIQUE (idempotency_key);
```

MySQL 8.4는 `CHECK` 제약을 실제로 강제한다 (8.0.16 이전에는 파싱만 하고 무시했다).

판정 기준 (등급 C. 근거 없음)

| 규칙 유형 | DB 제약으로 표현 |
|-----------|------------------|
| 값 범위 (수량 0 이상, 비율 0~100) | CHECK 필수 |
| 유일성 (멱등 키, 외부 거래 번호) | UNIQUE 필수 |
| 필수 값 | NOT NULL 필수 |
| 참조 관계 | 외래 키 권장. 대량 삭제 성능 문제가 있으면 정합성 검사로 대체 |
| 상태 전이 규칙 | 애플리케이션에서. 제약으로 표현하기 어렵다 |
| 두 참조의 조합 | **애플리케이션에서.** 조상까지 올라가야 해서 CHECK 범위 밖이다 |
| 여러 행의 합계 | **애플리케이션에서.** 잠금이 함께 필요하다 |

아래 둘은 DB가 못 막는다는 점이 같지만 이유가 다르다.
상태 전이는 이전 상태를 알아야 하고, 조합과 합계는 다른 행을 읽어야 한다.
**표현이 어려운 것이 아니라 CHECK가 자기 행만 볼 수 있어서 원리적으로 불가능하다.**
그래서 이 셋은 제약을 채우는 것으로 끝나지 않고 검증에서 반복해서 확인해야 한다.

애플리케이션 검증과 DB 제약은 중복이 아니라 계층 방어다.
전자는 친절한 오류 메시지를 위한 것이고, 후자는 데이터가 절대 깨지지 않게 하기 위한 것이다.

## 4. 트랜잭션 경계

점검 항목
* `[코드]` `DI-4-01` 트랜잭션 범위가 비즈니스 단위와 일치하는가
* `[코드]` `DI-4-02` 트랜잭션 안에서 외부 API를 호출하지 않는가
* `[코드]` `DI-4-03` 트랜잭션이 필요 이상으로 길지 않은가

checked 예외의 롤백 동작은 신뢰성 문서의 `REL-4-02`가 소유한다. 같은 사안이 두 문서에 있어 이쪽을 정리했다.

판정 기준 (등급 C. 근거 없음)

| 항목 | 기준 | 조치 |
|------|------|------|
| 트랜잭션 지속 시간 | 100ms 이하 | 초과 시 범위 재검토 |
| 트랜잭션 지속 시간 상한 | 1초 | 초과는 차단 대상. 배치는 별도 기준 |
| 트랜잭션 내 외부 호출 | 0건 | 예외 없음 |
| 트랜잭션 내 갱신 행 수 | 1000행 이하 | 초과 시 청크 분할 |

```java
// 점검 대상: 트랜잭션 안에서 외부 호출 -> 외부가 느리면 DB 커넥션과 락을 오래 점유
@Transactional
public void submit(SubmitRequest req) {
    Request saved = requestRepository.save(new Request(req));
    externalClient.execute(saved);   // 3초 대기 동안 트랜잭션과 락 유지
}

// 개선: 외부 호출을 트랜잭션 밖으로 빼고 상태로 연결
public void submit(SubmitRequest req) {
    Request saved = createPending(req);                       // 짧은 트랜잭션
    ExternalResult result = externalClient.execute(saved);    // 트랜잭션 밖
    complete(saved.getId(), result);                          // 짧은 트랜잭션
}
```

장시간 트랜잭션은 코드 리뷰만으로 잡히지 않는다. 운영에서 탐지한다.

```sql
-- 개선: 60초 이상 열려 있는 트랜잭션을 주기적으로 탐지한다
SELECT trx_id, trx_started, trx_mysql_thread_id, trx_query,
       TIMESTAMPDIFF(SECOND, trx_started, NOW()) AS elapsed_sec
FROM information_schema.innodb_trx
WHERE TIMESTAMPDIFF(SECOND, trx_started, NOW()) > 60;
```

## 5. 격리 수준과 이상 현상

MySQL 8.4 InnoDB의 기본 격리 수준은 REPEATABLE READ다.

| 격리 수준 | 방지되는 이상 현상 |
|-----------|--------------------|
| READ UNCOMMITTED | 없음 |
| READ COMMITTED | 더티 리드 |
| REPEATABLE READ | 더티 리드, 반복 불가능 읽기 |
| SERIALIZABLE | 위 전부와 팬텀 리드 |

주의할 점은 **격리 수준이 갱신 손실을 자동으로 막아 주지 않는다**는 것이다.
애플리케이션이 읽고 계산해서 쓰는 흐름(read-modify-write)은 격리 수준과 무관하게 잠금이나 원자적 갱신이 필요하다.

## 6. 분산 환경의 정합성

트랜잭션은 서비스 경계나 외부 시스템을 넘지 못한다.

점검 항목
* `[설계]` `DI-6-01` 서비스 간 작업에 보상 트랜잭션이 정의되어 있는가
* `[코드]` `DI-6-02` 이벤트 발행과 DB 커밋이 원자적인가
* `[코드]` `DI-6-03` 소비자가 중복 수신에 대비해 멱등한가
* `[인프라]` `DI-6-04` 처리 실패한 메시지가 유실되지 않고 격리되는가 (DLQ)

DB 커밋과 메시지 발행 사이에 장애가 나면 둘이 어긋난다.
아웃박스 패턴은 이벤트를 같은 트랜잭션 안에서 테이블에 저장하고, 별도 프로세스가 그 테이블을 읽어 발행한다.

```java
// 개선: 커밋과 이벤트 기록을 하나의 트랜잭션으로 묶는다
@Transactional
public void submit(SubmitRequest req) {
    Request saved = requestRepository.save(new Request(req));
    outboxRepository.save(OutboxEvent.submitted(saved));   // 같은 트랜잭션
}
```

메시지는 최소 한 번(at-least-once) 전달이 일반적이므로, 소비자는 반드시 멱등해야 한다.

판정 기준 (등급 C. 근거 없음)

| 항목 | 시작값 |
|------|--------|
| 아웃박스 발행 지연 | 5초 이내 |
| 아웃박스 미발행 적체 | 100건 초과 시 경보 |
| 메시지 재시도 | 3회 후 DLQ 이동 |
| DLQ 적체 | 1건이라도 있으면 확인 대상 |

## 7. 정합성 검증

버그는 결국 새어 나온다. 어긋난 상태를 탐지하는 장치를 함께 만든다.

점검 항목
* `[프로세스]` `DI-7-01` 주기적 정합성 검사가 실행되는가
* `[인프라]` `DI-7-02` 어긋남을 발견했을 때 알림이 가는가
* `[프로세스]` `DI-7-03` 정정 절차가 기록으로 남는가
* `[설계]` `DI-7-04` 검사 대상과 허용 오차가 정의되어 있는가

탐지 없이 운영하면 몇 달 뒤 정산 시점에 원인 불명의 차이를 만나게 된다.

### 검사 대상과 주기 (예시값)

아래는 검사 항목의 유형이다. 구체적인 대상은 서비스의 도메인에 맞게 채운다.

| 검사 유형 | 예 | 주기 | 허용 오차 | 초과 시 |
|-----------|-----|------|-----------|---------|
| 집계값 vs 원본 합계 | 캐시된 잔여 수량 vs 개별 행 SUM | 1시간 | 0 | 경보 |
| 우리 기록 vs 외부 시스템 기록 | 처리 완료 건 vs 외부 응답 대사 | 일 1회 | 0 | 즉시 경보 |
| 양방향 금액 대사 | 청구액 합계 vs 수납액 합계 | 일 1회 | 0 | 즉시 경보 |
| 상태 이력의 연속성 | 허용되지 않은 상태 전이 존재 여부 | 일 1회 | 0 | 조사 |
| 고아 데이터 | 부모가 사라진 자식 행 | 일 1회 | 0 | 조사 |

금전이 걸린 항목은 허용 오차가 없다. 1원이라도 어긋나면 원인을 찾는다.
금전을 다루지 않는 서비스라면 그 자리에 서비스의 핵심 불변식(항상 참이어야 하는 조건)을 넣는다.

```sql
-- 유형 1: 부모가 완료로 기록되었는데 자식 합계가 맞지 않는 건
SELECT r.id AS request_id,
       r.total_amount,
       COALESCE(SUM(x.amount), 0) AS settled_amount
FROM request r
LEFT JOIN request_item x
       ON x.request_id = r.id AND x.status = 'SETTLED'
WHERE r.status = 'COMPLETED'
  AND r.created_at >= CURRENT_DATE - INTERVAL 1 DAY
GROUP BY r.id, r.total_amount
HAVING r.total_amount <> COALESCE(SUM(x.amount), 0);
```

```sql
-- 유형 2: 제약을 우회해 들어온 범위 밖의 값
SELECT id, resource_id, remaining_qty
FROM resource_allocation
WHERE remaining_qty < 0
   OR remaining_qty > total_qty;
```

### 정정 절차

```
불일치 발견 시

1. 즉시 기록: 검출 시각, 대상 식별자, 양쪽 값, 차이
2. 영향 범위 확인: 같은 조건의 다른 행에도 발생했는지 조회
3. 확산 차단: 원인이 코드면 해당 경로를 먼저 막는다 (기능 스위치)
4. 원인 규명 후 정정. 원인을 모른 채 값만 맞추지 않는다
   값만 맞추면 같은 문제가 반복되고, 다음에는 탐지도 늦어진다
5. 정정 내역 기록: 실행자, 시각, 실행한 SQL, 영향 행 수, 사유
6. 재발 방지: 제약 추가, 잠금 도입, 검사 항목 추가 중 하나 이상
```

정정 SQL은 반드시 트랜잭션 안에서 `SELECT`로 대상을 먼저 확인한 뒤 실행하고, 실행 결과 행 수가 예상과 일치하는지 확인한 후에 커밋한다.

## 8. 측정 지표

| 지표 | 의미 | 목표 (예시값) |
|------|------|---------------|
| 정합성 검사 불일치 건수 | 실제 데이터 오염 수준 | 금전 항목 0건 |
| 낙관적 잠금 충돌률 | 잠금 전략 적합성 판단 | 10% 초과 시 전략 변경 |
| 교착 상태 발생 건수 | `SHOW ENGINE INNODB STATUS` | 절대값보다 추세를 본다 |
| 제약 위반 예외 발생 건수 | 애플리케이션 검증의 빈틈 | 0건 |
| 중복 처리 탐지 건수 | 멱등성 구현의 실효성 | 탐지는 정상, 통과는 사고 |
| 장기 트랜잭션 발생 건수 | 잠금 점유 위험 | 1초 초과 0건 |

## 9. 관련 문서

* 멱등성과 재시도: [qa-reliability-rationale.md](./qa-reliability-rationale.md)
* 정확성과 성능의 충돌: [qa-tradeoffs-rationale.md](./qa-tradeoffs-rationale.md)
* 잠금이 성능에 주는 영향: [qa-performance-efficiency-rationale.md](./qa-performance-efficiency-rationale.md)

## 10. 참고 문헌

| 항목 | 링크 |
|------|------|
| MySQL 8.4 Reference Manual, InnoDB 시스템 변수 | https://dev.mysql.com/doc/refman/8.4/en/innodb-parameters.html |
| MySQL 8.4 Reference Manual, InnoDB 오류 처리(교착과 재시도) | https://dev.mysql.com/doc/refman/8.4/en/innodb-error-handling.html |
