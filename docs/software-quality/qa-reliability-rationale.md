# 신뢰성 점검 항목의 근거

판정용 항목 목록은 [qa-reliability-guideline.md](./qa-reliability-guideline.md) 에 있다.
이 문서는 왜 그 기준인지와 예시를 담는다.

명시된 조건에서 명시된 기간 동안 의도한 기능을 수행하는 정도를 뜻한다.

하위 특성
* **무결함성(faultlessness)**: 정상 운영 중 결함 없이 동작
* **가용성(availability)**: 필요할 때 접근 가능
* **결함 허용성(fault tolerance)**: 결함이 있어도 동작 유지
* **복구성(recoverability)**: 장애 후 데이터와 상태를 복원

코드 한 줄을 보고 판단하기 어렵고 시스템 구성 단위에서 결정되는 영역이라, 설계 단계에서 명시적으로 다루지 않으면 통째로 누락되기 쉽다.
이 문서의 점검 항목은 `[인프라]`와 `[프로세스]` 비중이 높다.

> **수치에는 근거 등급이 표시되어 있다.**
> A는 산술로 도출된 값, B는 출처가 있는 값(링크 표기), C는 근거 없이 정한 예시값이다.
> C로 표시된 값은 그대로 채택하지 말고 측정 후 팀이 확정한다.
> 등급 정의는 quality-attributes.md의 "판정 기준 수치의 성격"을 참고한다.

## 1. 가용성은 숫자로 정의한다

아래 표는 등급 A(산술 도출)이므로 그대로 사용한다.

| 가용성 | 연간 허용 다운타임 | 월간 허용 다운타임 |
|--------|--------------------|--------------------|
| 99% | 약 3.65일 | 약 7.3시간 |
| 99.9% | 약 8.76시간 | 약 43.8분 |
| 99.95% | 약 4.38시간 | 약 21.9분 |
| 99.99% | 약 52.6분 | 약 4.4분 |
| 99.999% | 약 5.26분 | 약 26초 |

99.9%를 목표로 잡는 순간 무중단 배포, 헬스체크, 이중화가 선택이 아니라 요구사항이 된다.
배포 때마다 5분씩 내리면 월 2회 배포만으로 99.98%를 이미 소진한다.

점검 항목
* `[설계]` `REL-1-01` 기능 등급별로 가용성 목표를 다르게 정했는가
* `[설계]` `REL-1-02` 목표가 백분위수와 기간을 포함한 문장으로 적혀 있는가
* `[프로세스]` `REL-1-03` 목표 대비 실적을 정기적으로 확인하는 자리가 있는가

판정 기준 (등급 C. 근거 없음)

| 기능 등급 | 판단 기준 | 가용성 목표 |
|-----------|-----------|-------------|
| 핵심 거래 | 실패 시 금전 손실이나 데이터 유실이 발생 | 99.95% |
| 주요 조회 | 실패 시 서비스의 주 사용 흐름이 막힘 | 99.9% |
| 부가 기능 | 없어도 주 흐름은 동작함 | 99.5% |
| 내부 도구 | 사용자 대면이 아님 | 99% |

전체 시스템에 하나의 목표를 걸면 부가 기능 때문에 핵심 거래의 예산이 깎인다.
목표 문장은 다음 형태로 적는다.

```
[핵심 거래 API 이름]은 30일 이동 기간 기준으로
성공 응답 비율 99.95% 이상, p99 응답시간 300ms 이하를 유지한다.
```

## 2. 외부 연동은 반드시 실패한다

외부 시스템은 느려지거나 죽는다는 전제로 짠다.
가장 위험한 것은 죽는 경우가 아니라 **느려지는 경우**다. 응답이 없으면 우리 스레드가 묶여 전체 서비스가 멈춘다.

### 타임아웃

점검 항목
* `[코드]` `REL-2-01` 모든 외부 호출에 연결 타임아웃과 읽기 타임아웃이 설정되어 있는가
* `[인프라]` `REL-2-02` 타임아웃 값이 상위 호출자의 타임아웃보다 짧은가 (타임아웃 예산 배분)
* `[인프라]` `REL-2-03` DB 커넥션 획득과 쿼리 실행에도 타임아웃이 있는가

판정 기준 (등급 C. 근거 없음)

| 구간 | 연결 | 읽기 | 근거 |
|------|------|------|------|
| API 게이트웨이 | - | 10s | 사용자 인내 한계 |
| 서비스 간 호출 | 1s | 5s | 게이트웨이 예산의 절반 |
| 외부 연동 (결제, 알림, 인증 등) | 1s | 3s | 상위 예산 안에서 재시도 여유 확보 |
| DB 커넥션 획득 | 3s | - | 풀 고갈을 빠르게 드러냄 |
| DB 쿼리 | - | 5s | 장기 쿼리로 인한 커넥션 점유 방지 |

타임아웃은 안쪽으로 갈수록 짧아야 한다.
상위 10초, 하위 3초 식으로 예산을 나눈다. 반대가 되면 상위가 먼저 끊겨 하위 작업이 고아가 된다.

```java
// 점검 대상: 타임아웃 없음. 외부가 30초 응답하면 우리 스레드도 30초 묶인다
RestClient client = RestClient.create();

// 개선: 명시적 타임아웃
@Bean
public RestClient externalClient(RestClient.Builder builder) {
    SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
    factory.setConnectTimeout(Duration.ofSeconds(1));
    factory.setReadTimeout(Duration.ofSeconds(3));
    return builder.requestFactory(factory).build();
}
```

DB 쪽 타임아웃은 코드가 아니라 설정에서 정한다.

```yaml
# 개선: 커넥션 획득과 쿼리 실행에 각각 상한을 둔다
spring:
  datasource:
    hikari:
      connection-timeout: 3000      # 커넥션 획득 대기 상한
      validation-timeout: 1000
      max-lifetime: 1740000         # MySQL wait_timeout(기본 28800s)보다 짧게
  jpa:
    properties:
      jakarta.persistence.query.timeout: 5000
```

`max-lifetime`은 DB의 `wait_timeout`보다 반드시 짧아야 한다.
그렇지 않으면 DB가 이미 끊은 커넥션을 풀이 살아 있다고 판단해 간헐적 연결 오류가 발생한다.

관련 기본값 (등급 B)

| 항목 | 기본값 | 출처 |
|------|--------|------|
| MySQL `wait_timeout`, `interactive_timeout` | 28800초 (8시간) | MySQL 8.4 Reference Manual |
| MySQL `max_execution_time` | 0 (비활성) | MySQL 8.4 Reference Manual |
| HikariCP `connectionTimeout` | 30000ms | HikariCP 문서 |
| HikariCP `maxLifetime` | 1800000ms (30분) | HikariCP 문서 |

위 예시의 `max-lifetime: 1740000`(29분)은 기본값 30분에서 DB 종료 시점과 겹치지 않도록 약간 줄인 값이며 등급 C다.

### 재시도와 멱등성

재시도를 붙이려면 반드시 멱등해야 한다. 타임아웃이 났다고 상태를 바꾸는 요청을 그냥 재시도하면 같은 작업이 두 번 실행된다.
금전이 걸린 연동이라면 곧바로 이중 청구가 된다.

점검 항목
* `[코드]` `REL-2-04` 재시도 대상 연산이 멱등한가
* `[설계]` `REL-2-05` 재시도 가능한 오류와 불가능한 오류를 구분했는가
* `[코드]` `REL-2-06` 재시도 간격에 지수 백오프와 지터를 적용했는가
* `[코드]` `REL-2-07` 재시도 횟수에 상한이 있는가
* `[인프라]` `REL-2-08` 재시도 총 소요 시간이 상위 타임아웃 예산 안에 들어오는가

판정 기준 (지터 방식은 등급 B, 나머지 수치는 등급 C)

지터의 필요성과 방식은 AWS Architecture Blog의 Exponential Backoff And Jitter에 근거한다.
출처: https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/

이 글은 지수 백오프만으로는 재시도가 특정 시점에 몰리는 문제를 해결하지 못하며, 무작위성을 더해야 분산된다는 점을 시뮬레이션으로 보인다. 세 가지 방식을 제시한다.

| 방식 | 계산 | 특징 |
|------|------|------|
| Full Jitter | `random(0, cap)` | 분산 효과가 가장 크다. 대기가 0에 가까울 수 있다 |
| Equal Jitter | `cap/2 + random(0, cap/2)` | 최소 대기를 보장한다. 429 같은 스로틀링 응답에 적합 |
| Decorrelated Jitter | `min(cap, random(base, prev*3))` | AWS SDK 계열의 기본 방식 |

| 항목 | 값 | 등급 |
|------|-----|------|
| 지터 적용 | 필수 | B. 위 출처 |
| 지터 방식 | 일반 재시도는 Full Jitter, 스로틀링 응답은 Equal Jitter | B |
| 최대 재시도 횟수 | 3회 | C. 팀에서 확정 |
| 초기 대기 | 200ms | C. 팀에서 확정 |
| 배수 | 2배 | C. 팀에서 확정 |
| 재시도 총 시간 | 상위 타임아웃 예산 안 | C. 예산 계산에 따라 결정 |

```java
// 점검 대상: 타임아웃 시 무조건 재시도 -> 중복 실행 가능
for (int i = 0; i < 3; i++) {
    try { return externalClient.execute(request); }
    catch (TimeoutException e) { /* 재시도 */ }
}

// 개선: 멱등 키로 중복 실행을 막는다
public ExternalResult execute(Request request, String idempotencyKey) {
    return externalRequestRepository.findByIdempotencyKey(idempotencyKey)
        .map(ExternalResult::from)
        .orElseGet(() -> doExecute(request, idempotencyKey));
}
```

DB 레벨에서 최종 방어선을 만든다.

```sql
ALTER TABLE external_request
    ADD CONSTRAINT uk_external_request_idem UNIQUE (idempotency_key);
```

재시도 가능 여부는 오류 코드로 계약에 명시한다.

| 상황 | 재시도 | 이유 |
|------|--------|------|
| 연결 실패, 타임아웃, 503 | 가능 | 일시적 가용성 문제 |
| 429 (레이트 리밋) | 가능. 단 Retry-After 준수 | 서버가 대기 시간을 지정 |
| 500 | 조건부 | 멱등한 연산만 |
| 400, 422 (잘못된 인자) | 불가 | 같은 요청은 계속 실패한다 |
| 401, 403 | 불가 | 자격 갱신 없이는 동일 결과 |

### 서킷 브레이커와 격벽

점검 항목
* `[인프라]` `REL-2-09` 실패율이 임계치를 넘으면 호출을 끊고 빠르게 실패하는가
* `[인프라]` `REL-2-10` 외부 연동별로 스레드풀 또는 커넥션풀이 분리되어 있는가
* `[설계]` `REL-2-11` 차단 상태에서의 대체 동작(fallback)이 정의되어 있는가
* `[설계]` `REL-2-12` 대체 동작이 안전한지 검토했는가

판정 기준 (등급 B. Resilience4j 공식 문서의 기본값 기준)

Resilience4j 2.2.0의 `CircuitBreakerConfig` 기본값은 다음과 같다.
출처: https://resilience4j.readme.io/docs/circuitbreaker

| 설정 | 라이브러리 기본값 | 이 문서의 제안 | 제안 사유 |
|------|-------------------|----------------|-----------|
| `failureRateThreshold` | 50% | 50% (그대로) | 기본값 사용 |
| `minimumNumberOfCalls` | 100건 | 20건 | 호출량이 적은 연동에서는 100건이 모이기 전에 장애가 지나간다 |
| `slidingWindowSize` | 100 | 연동별 호출량에 맞춤 | 최소 호출 수와 함께 조정 |
| `waitDurationInOpenState` | 60초 | 30초 | 회복 확인 주기를 앞당김 |
| `permittedNumberOfCallsInHalfOpenState` | 10건 | 5건 | 회복 확인 비용 절감 |
| `slowCallRateThreshold` | 100% | 50% | 완전 실패 전에 느린 호출로 차단 |
| `slowCallDurationThreshold` | 60초 | 읽기 타임아웃의 60% | 타임아웃 이전에 감지 |

기본값에서 벗어난 값(20건, 30초, 5건, 50%)은 위 사유가 그 서비스에 해당할 때만 쓴다.
해당하지 않으면 기본값을 그대로 두는 편이 안전하다.

```yaml
# 개선: 연동별로 서킷과 격벽을 따로 구성한다
resilience4j:
  circuitbreaker:
    instances:
      externalPrimary:
        failure-rate-threshold: 50
        slow-call-duration-threshold: 2s
        slow-call-rate-threshold: 50
        minimum-number-of-calls: 20
        wait-duration-in-open-state: 30s
        permitted-number-of-calls-in-half-open-state: 5
  bulkhead:
    instances:
      externalPrimary:
        max-concurrent-calls: 20      # 핵심 연동이 쓸 수 있는 동시 호출 상한
      externalOptional:
        max-concurrent-calls: 10      # 부가 기능 연동은 더 좁게
```

격벽(bulkhead)이 없으면 부가 기능 연동 한 곳의 지연이 전체 스레드풀을 잠식해 핵심 거래까지 멈춘다.
연동별로 자원을 나누면 장애가 그 구획 안에 갇힌다.

대체 동작은 무조건 기본값 반환이 아니다.

| 기능 유형 | 대체 동작 | 이유 |
|-----------|-----------|------|
| 부가 정보 목록 | 빈 배열 | 없어도 주 흐름에 지장 없다 |
| 예측값, 추정 정보 | 안내 문구로 대체 | 부정확한 값보다 미표시가 낫다 |
| 한정 자원의 잔여 수량 | 대체값 금지. 실패 처리 | 잘못된 값은 초과 할당으로 이어진다 |
| 금전 처리 | 대체값 금지. 실패 처리 | 되돌리기 어려운 사고 |

## 3. 결함 허용과 부하 차단

점검 항목
* `[인프라]` `REL-3-01` 과부하 시 전체가 느려지는 대신 일부를 거절하는가 (load shedding)
* `[인프라]` `REL-3-02` 큐 길이와 대기 시간에 상한이 있는가
* `[설계]` `REL-3-03` 우선순위가 낮은 기능을 먼저 끌 수 있는가 (graceful degradation)
* `[프로세스]` `REL-3-04` 기능을 끄는 스위치를 배포 없이 조작할 수 있는가

모두를 조금씩 느리게 만드는 것보다 일부를 즉시 거절하는 편이 낫다.
전자는 전원 실패로 끝나고, 후자는 대부분이 성공한다.

판정 기준 (등급 C. 근거 없음)

| 항목 | 시작값 | 근거 |
|------|--------|------|
| 요청 대기 큐 길이 | 스레드풀 크기의 2배 | 그 이상 쌓이면 처리 전에 클라이언트가 포기한다 |
| 큐 대기 시간 상한 | 1초 | 대기가 길면 이미 무의미한 요청이다 |
| 거절 시작 지점 | CPU 사용률 80% 지속 | 포화 직전에 차단해 완전 정지를 막는다 |

```yaml
# 개선: 무한 대기 대신 상한을 두고 초과분은 즉시 거절한다
server:
  tomcat:
    threads:
      max: 200
    accept-count: 400          # 대기 큐 상한. 초과 시 연결 거절
    connection-timeout: 5s
```

기능 차단 스위치는 배포 없이 조작 가능해야 한다.

```java
// 개선: 부가 기능을 설정으로 즉시 끌 수 있게 한다
@Value("${feature.optional-enrichment.enabled:true}")
private boolean enrichmentEnabled;

public List<Item> enrich(Long userId) {
    if (!enrichmentEnabled) {
        return List.of();     // 장애 시 스위치를 내려 부하를 줄인다
    }
    return optionalClient.fetch(userId);
}
```

장애 한복판에서 배포를 해야만 기능을 끌 수 있다면, 그 스위치는 없는 것과 같다.

## 4. 복구성

이 절은 복구 가능한 **성질**을 설계하는 것을 다룬다.
실제로 서버가 죽었을 때 사람이 수행하는 절차(페일오버, 롤백 실행, 재기동 후 복구, 사후 분석)는 [qa-incident-response-rationale.md](./qa-incident-response-rationale.md)에 있다.

점검 항목
* `[설계]` `REL-4-01` 트랜잭션 경계가 복구 단위와 일치하는가
* `[코드]` `REL-4-02` checked 예외에서 롤백이 동작하는가
* `[프로세스]` `REL-4-03` 백업뿐 아니라 복원을 실제로 리허설했는가
* `[설계]` `REL-4-04` RPO와 RTO를 숫자로 정의했는가
* `[인프라]` `REL-4-05` 백업이 원본과 다른 장애 도메인에 저장되는가

Spring `@Transactional`은 기본적으로 unchecked 예외에만 롤백한다.

```java
// 점검 대상: checked 예외는 롤백되지 않아 데이터가 어긋난 채 커밋된다
@Transactional
public void settle() throws IOException {
    recordRepository.save(record);
    fileExporter.export(record);   // IOException 발생 시 record는 커밋됨
}

// 개선 1: 롤백 대상 지정
@Transactional(rollbackFor = IOException.class)

// 개선 2: 도메인 예외(unchecked)로 변환
catch (IOException e) {
    throw new SettlementFailedException(record.getId(), e);
}
```

판정 기준 (등급 C. 근거 없음)

| 데이터 등급 | 판단 기준 | RPO | RTO |
|-------------|-----------|-----|-----|
| 금전, 자원 이동 기록 | 유실 시 금전 손실이나 법적 문제 발생 | 0 (손실 불가) | 1시간 |
| 사용자 생성 거래 데이터 | 유실 시 사용자가 다시 만들 수 없음 | 5분 | 4시간 |
| 운영 기준 데이터 | 유실 시 재입력 가능하나 비용이 큼 | 1시간 | 8시간 |
| 파생 데이터 | 원본에서 재생성 가능 | 재생성 가능 | 24시간 |

RPO 0을 요구하는 데이터는 바이너리 로그 동기 복제가 필요하고, 이는 쓰기 성능 비용을 수반한다.
등급을 나누지 않고 전부 RPO 0으로 잡으면 감당할 수 없는 비용이 된다.

### 복원 리허설 절차

복원해 본 적 없는 백업은 백업이 아니다.
다음을 분기 1회 이상 수행하고 기록한다.

```
1. 대상 선정: 운영 DB의 특정 시점 스냅샷 (최근 7일 이내 임의 시점)
2. 격리 환경에 복원 (운영과 분리된 네트워크)
3. 측정 항목
   - 복원 명령 시작부터 서비스 기동까지 실제 소요 시간 -> RTO 대비 판정
   - 복원된 데이터의 최신 시점 -> RPO 대비 판정
   - 복원 절차 중 문서에 없던 수동 개입 횟수
4. 검증: 핵심 테이블 행 수 대조, 최근 거래 10건의 정합성 확인
5. 기록: 소요 시간, 실패 지점, 문서 갱신 사항
```

실제 소요 시간이 RTO를 넘으면 목표를 낮추거나 절차를 개선한다.
둘 다 하지 않고 목표만 문서에 남겨 두는 것이 가장 나쁘다.

## 5. 배포와 헬스체크

점검 항목
* `[인프라]` `REL-5-01` 헬스체크가 의존 컴포넌트 상태를 반영하는가
* `[인프라]` `REL-5-02` 기동 완료 전에 트래픽을 받지 않는가 (readiness와 liveness 분리)
* `[인프라]` `REL-5-03` 종료 시 처리 중인 요청을 마치고 내려가는가 (graceful shutdown)
* `[인프라]` `REL-5-04` liveness가 외부 의존성 상태에 좌우되지 않는가

```yaml
# 개선: 처리 중인 요청을 마칠 시간을 주고, 두 종류의 헬스체크를 분리한다
server:
  shutdown: graceful
spring:
  lifecycle:
    timeout-per-shutdown-phase: 30s
management:
  endpoint:
    health:
      probes:
        enabled: true               # /health/liveness, /health/readiness 분리
  health:
    db:
      enabled: true
```

판정 기준 (등급 C. 근거 없음)

| 항목 | 시작값 | 근거 |
|------|--------|------|
| graceful shutdown 대기 | 30초 | 대부분의 요청이 끝나는 시간 |
| readiness 실패 임계 | 연속 3회 | 순간적 지연으로 트래픽이 끊기는 것 방지 |
| liveness 실패 임계 | 연속 5회 | 재시작은 최후 수단이므로 더 보수적으로 |
| 배포 간 대기 | 이전 인스턴스 종료 확인 후 | 동시 교체로 용량이 부족해지는 것 방지 |

liveness가 DB 상태까지 확인하면, DB 순단 시 애플리케이션이 통째로 재시작되며 상황이 악화된다.
liveness는 프로세스 자체의 생존만 보고, 의존성 상태는 readiness에서 본다.

## 6. 측정 지표

| 지표 | 의미 | 경보 기준 (예시값) |
|------|------|--------------------|
| 가용성 SLI | 성공 요청 수 / 전체 요청 수 | 등급별 목표 미달 |
| MTBF | 평균 장애 간격 | 추세 악화 시 검토 |
| MTTR | 평균 복구 시간 | RTO 초과 |
| 에러 예산 소진율(burn rate) | SLO 대비 소진 속도 | 아래 SRE Workbook 기준 참고 |
| 서킷 개방 횟수 | 외부 연동 불안정 정도 | 일 3회 이상 |
| 배포 실패율 | 변경으로 인한 장애 비율 | 15% 초과 |

에러 예산 개념이 유용하다.
SLO가 99.9%면 월 43.8분의 실패가 허용된 예산이다. 예산이 남으면 배포 속도를 올리고, 소진되면 안정화에 집중한다.

소진 속도에 대한 경보 임계는 Google SRE Workbook의 다중 구간 소진율(multiwindow multi-burn-rate) 기준을 따른다 (등급 B).
출처: https://sre.google/workbook/alerting-on-slos/

| 소진 속도 | 관측 구간 | 의미 (30일 예산 기준) | 대응 |
|-----------|-----------|------------------------|------|
| 14.4배 | 1시간 | 1시간에 예산의 2% 소진 | 즉시 호출(page) |
| 6배 | 6시간 | 6시간에 예산의 5% 소진 | 즉시 호출(page) |
| 1배 | 3일 | 3일에 예산의 10% 소진 | 티켓 |

짧은 구간과 긴 구간을 함께 보아 두 조건이 동시에 충족될 때만 발화시키면 일시적 스파이크로 인한 오탐이 줄어든다.
짧은 구간은 긴 구간의 12분의 1로 잡는 것이 출처의 권고다. 예를 들어 1시간 구간에는 5분 구간을 함께 본다.

## 7. 관련 문서

* 장애 감지와 진단: [qa-observability-rationale.md](./qa-observability-rationale.md)
* 실제 장애 발생 시 대응 절차: [qa-incident-response-rationale.md](./qa-incident-response-rationale.md)
* 데이터 복구와 정합성: [qa-data-integrity-rationale.md](./qa-data-integrity-rationale.md)
* 가용성과 정합성의 충돌: [qa-tradeoffs-rationale.md](./qa-tradeoffs-rationale.md)

## 8. 참고 문헌

| 항목 | 링크 |
|------|------|
| Google SRE Workbook, Alerting on SLOs (소진율 기준) | https://sre.google/workbook/alerting-on-slos/ |
| AWS Architecture Blog, Exponential Backoff And Jitter | https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/ |
| Resilience4j CircuitBreaker 기본값 | https://resilience4j.readme.io/docs/circuitbreaker |
| MySQL 8.4 Reference Manual, InnoDB 시스템 변수 | https://dev.mysql.com/doc/refman/8.4/en/innodb-parameters.html |
