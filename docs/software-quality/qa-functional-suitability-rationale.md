# 기능 적합성 점검 항목의 근거

판정용 항목 목록은 [qa-functional-suitability-guideline.md](./qa-functional-suitability-guideline.md) 에 있다.
이 문서는 왜 그 기준인지와 예시를 담는다.

명시된 요구와 암묵적 요구를 실제로 충족하는 정도를 뜻한다.

하위 특성
* **기능 완전성**: 필요한 기능이 빠짐없이 있는가
* **기능 정확성**: 올바른 결과를 내는가
* **기능 적절성**: 그 기능이 목적 달성에 적합한가

> **수치에는 근거 등급이 표시되어 있다.**
> A는 산술로 도출된 값, B는 출처가 있는 값(링크 표기), C는 근거 없이 정한 예시값이다.
> C로 표시된 값은 그대로 채택하지 말고 측정 후 팀이 확정한다.
> 등급 정의는 quality-attributes.md의 "판정 기준 수치의 성격"을 참고한다.

## 1. 백엔드에서 무너지는 지점

기능 자체를 못 만드는 경우는 드물다. 문제는 거의 항상 다음 세 곳에서 생긴다.

* 정상 경로만 구현하고 예외 경로가 비어 있다
* 경계값(0, null, 빈 컬렉션, 최대값, 음수)을 처리하지 않는다
* 부수 효과가 이름과 어긋나 호출자가 잘못 쓴다

개발자는 만들면서 정상 시나리오를 먼저 떠올리기 때문에 예외 경로는 자연스럽게 비어 있게 된다.

## 2. 예외 경로 누락

점검 항목
* `[코드]` `FUN-2-01` 외부 호출이 실패했을 때의 흐름이 구현되어 있는가
* `[코드]` `FUN-2-02` 실패 시 이미 만들어진 데이터가 불일치 상태로 남지 않는가
* `[설계]` `FUN-2-03` 부분 성공 상태를 표현할 수 있는가
* `[코드]` `FUN-2-04` 결과를 모르는 상태(타임아웃)를 실패와 구분하는가

```java
// 점검 대상: 성공 경로만 처리. 실패하면 우리 기록만 남고 외부는 실행 안 된 불일치 상태
public void submit(SubmitRequest req) {
    Request saved = requestRepository.save(new Request(req));
    externalClient.execute(saved);
}

// 개선: 실패를 상태로 표현하고 후속 처리 경로를 만든다
@Transactional
public Request submit(SubmitRequest req) {
    Request saved = requestRepository.save(Request.pending(req));
    try {
        ExternalResult result = externalClient.execute(saved);
        saved.markCompleted(result.getTransactionId());
    } catch (ExternalException e) {
        saved.markFailed(e.getReason());
        throw new RequestFailedException(saved.getId(), e);
    }
    return saved;
}
```

외부 호출이 타임아웃된 경우는 실패가 아니라 **결과를 모르는 상태**다.
성공으로도 실패로도 확정할 수 없으므로 별도 상태(`UNKNOWN`, `PENDING_CONFIRM`)로 두고 조회로 확정한다.
이 구분은 [qa-reliability-rationale.md](./qa-reliability-rationale.md)의 멱등성 항목과 함께 본다.

판정 기준 (등급 C. 근거 없음)

| 항목 | 기준 |
|------|------|
| 외부 호출당 정의된 실패 분기 | 최소 3가지 (실패, 타임아웃, 예상 외 응답) |
| 미확정 상태의 확정 시도 | 5분 이내 자동 조회 |
| 미확정 상태 잔존 | 1시간 초과 시 경보 |

## 3. 경계값 처리

오류는 값의 양 끝에서 집중적으로 발생한다. 중간값은 대충 짜도 동작하기 때문에 경계를 따로 의식하지 않으면 놓친다.

점검 항목
* `[코드]` `FUN-3-01` 빈 입력, null, 0, 음수, 최대값을 처리하는가
* `[코드]` `FUN-3-02` 나눗셈 앞에 분모가 0이 될 가능성을 확인했는가
* `[코드]` `FUN-3-03` 페이지 크기, 조회 건수 등에 상한이 있는가
* `[코드]` `FUN-3-04` 상한을 클라이언트가 아니라 서버가 강제하는가

```java
// 점검 대상: 빈 리스트면 0으로 나눠 ArithmeticException, null이면 NPE
public int average(List<Integer> scores) {
    return scores.stream().mapToInt(i -> i).sum() / scores.size();
}

// 개선: 없음을 값이 아니라 타입으로 표현
public OptionalDouble average(List<Integer> scores) {
    if (scores == null || scores.isEmpty()) {
        return OptionalDouble.empty();
    }
    return scores.stream().mapToInt(Integer::intValue).average();
}
```

상한이 없는 조회는 기능 문제이자 성능 사고로 이어진다.

```java
// 점검 대상: size 제한이 없어 클라이언트가 size=1000000 을 보내면 서버가 죽는다
public Page<Record> list(int page, int size) {
    return recordRepository.findAll(PageRequest.of(page, size));
}

// 개선: 상한을 서버가 강제한다
private static final int MAX_PAGE_SIZE = 100;

public Page<Record> list(int page, int size) {
    int bounded = Math.min(Math.max(size, 1), MAX_PAGE_SIZE);
    return recordRepository.findAll(PageRequest.of(page, bounded));
}
```

테스트로 강제할 경계값 목록 (예시값)

| 입력 유형 | 반드시 검증할 값 |
|-----------|------------------|
| 컬렉션 | null, 빈 컬렉션, 1개, 상한, 상한+1 |
| 수량, 금액 | 0, 1, 음수, 최대값, 최대값+1 |
| 문자열 | null, 빈 문자열, 공백만, 최대 길이, 최대 길이+1 |
| 날짜 | 과거, 현재, 미래, 경계일(월말, 윤년 2월 29일) |
| 페이지 | 0페이지, 마지막 페이지, 범위 초과 페이지 |

## 4. 계산 정확성

금액과 수량 계산은 정확성이 곧 사고 여부를 가른다.

점검 항목
* `[코드]` `FUN-4-01` 금액 계산에 float, double을 쓰지 않는가
* `[코드]` `FUN-4-02` 반올림 정책(자리수, 모드)을 명시했는가
* `[설계]` `FUN-4-03` DB 컬럼 타입이 애플리케이션 타입과 정밀도가 맞는가
* `[코드]` `FUN-4-04` 총액을 여러 항목에 배분할 때 배분액의 합이 총액과 일치하는가

```java
// 점검 대상: 이진 부동소수라 0.1 + 0.2 != 0.3
double total = 0.1 + 0.2;

// 개선: BigDecimal 또는 최소 단위 정수(원 단위 long)
BigDecimal total = price.multiply(BigDecimal.valueOf(quantity))
                        .setScale(0, RoundingMode.HALF_UP);
```

```sql
-- 점검 대상: 금액에 부동소수 타입
amount DOUBLE NOT NULL,

-- 개선: 고정 소수점
amount DECIMAL(19,4) NOT NULL,
```

MySQL 8.4에서 `DECIMAL` 연산은 정확한 십진 연산으로 처리되고, `DOUBLE`은 근사값이다.
금액 합계를 `SUM(DOUBLE)`로 집계하면 건수가 늘수록 오차가 누적된다.

판정 기준 (등급 C. 근거 없음)

| 항목 | 기준 |
|------|------|
| 금액 표현 | `DECIMAL(19,4)` 또는 최소 단위 정수 `BIGINT` |
| 반올림 모드 | 금액은 `HALF_UP`. 정책이 다르면 명시 |
| 저장 자리수 | 원화는 소수점 0자리로 확정 후 저장 |
| 배분 계산 오차 | 0. 나머지는 마지막 항목에 몰아준다 |

```java
// 개선: 배분 후 합계가 총액과 어긋나지 않게 잔여를 마지막 항목에 흡수시킨다
long distributed = 0;
for (int i = 0; i < items.size() - 1; i++) {
    long share = totalToDistribute * items.get(i).getAmount() / totalAmount;
    items.get(i).apply(share);
    distributed += share;
}
items.get(items.size() - 1).apply(totalToDistribute - distributed);
```

각 항목을 독립적으로 반올림하면 합계가 총액과 1원씩 어긋난다.
부분 취소나 부분 정산에서 이 오차가 누적되면 장부가 맞지 않는다.

## 5. 부수 효과의 명확성

점검 항목
* `[코드]` `FUN-5-01` 조회처럼 보이는 메서드가 상태를 바꾸지 않는가
* `[코드]` `FUN-5-02` 반환값이 없는 메서드의 성공 여부를 호출자가 알 수 있는가

```java
// 점검 대상: 이름은 조회인데 내부에서 상태를 바꿈
public User getUser(Long id) {
    User u = userRepository.findById(id).orElseThrow();
    u.setLastAccessedAt(now());   // 호출자가 예측 못 하는 부수 효과
    return u;
}

// 개선: 의도를 이름에 드러내고 분리
public User getUser(Long id) { ... }
public void recordAccess(Long id) { ... }
```

의도하지 않은 부수 효과는 호출자가 예측할 수 없어 추적이 어려운 버그로 이어진다.

## 6. 요구사항 검증 절차

점검 항목
* `[프로세스]` `FUN-6-01` 요구사항과 테스트가 대응되어 추적 가능한가
* `[프로세스]` `FUN-6-02` 릴리스 전에 예외 시나리오를 함께 검증하는가
* `[프로세스]` `FUN-6-03` 운영 결함의 원인 유형을 집계하는가

```
기능 인수 검증 절차

1. 요구사항을 시나리오 단위로 분해 (정상 1개당 예외 최소 2개)
2. 각 시나리오에 대응하는 테스트 식별자 부여
3. 대응 테스트가 없는 시나리오 목록화 -> 릴리스 판정 대상
4. 릴리스 후 발생한 결함을 유형별로 분류
   (예외 경로 누락 / 경계값 / 계산 오류 / 요구 오해 / 기타)
5. 분기별로 유형 분포 확인. 가장 많은 유형에 점검 항목을 보강
```

결함을 유형별로 집계하지 않으면 어떤 점검을 강화해야 할지 알 수 없다.
"조심하자"는 대책은 다음에도 같은 결과를 낳는다.

## 7. 측정 지표

| 지표 | 의미 | 기준 (예시값) |
|------|------|---------------|
| 요구사항 커버리지 | 시나리오 중 테스트로 검증된 비율 | 예외 시나리오 포함 90% 이상 |
| 결함 밀도 | 코드 규모 대비 운영 결함 수 | 추세 악화 시 검토 |
| 결함 유출률 | 운영에서 발견된 결함 / 전체 결함 | 20% 이하 |
| 예외 경로 테스트 비율 | 실패 케이스를 검증하는 테스트 비율 | 전체 테스트의 40% 이상 |
| 미확정 상태 잔존 건수 | 결과를 모르는 외부 호출 | 1시간 초과 0건 |

정상 케이스만 검증하는 테스트는 정작 버그가 잘 생기는 영역을 비워 둔다.

```java
@Test
void 잔여_수량이_부족하면_요청에_실패한다() {
    Allocation alloc = new Allocation(resourceId, 0);
    assertThatThrownBy(() -> allocationService.reserve(alloc, 1))
        .isInstanceOf(InsufficientQuantityException.class);
}
```

## 8. 관련 문서

* 예외 경로와 실패 처리: [qa-reliability-rationale.md](./qa-reliability-rationale.md)
* 동시 수정 시의 정확성: [qa-data-integrity-rationale.md](./qa-data-integrity-rationale.md)
* 테스트 설계와 시험성: [qa-maintainability-rationale.md](./qa-maintainability-rationale.md)
