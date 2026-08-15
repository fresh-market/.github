# 관측 가능성 점검 항목의 근거

판정용 항목 목록은 [qa-observability-guideline.md](./qa-observability-guideline.md) 에 있다.
이 문서는 왜 그 기준인지와 예시를 담는다.

시스템의 외부 출력만으로 내부 상태를 파악할 수 있는 정도를 뜻한다.

ISO/IEC 25010:2023에 독립 특성으로 존재하지 않으며, 유지보수성의 분석성(analysability)을 시스템 운영 차원으로 확장한 개념이다.
코드 수준의 분석성은 [qa-maintainability-rationale.md](./qa-maintainability-rationale.md)에서 다루고, 이 문서는 운영 중인 시스템을 대상으로 한다.

예외 로그를 스택과 함께 남기는 수준에서 멈추기 쉬운 영역이다.
메트릭과 분산 추적, SLO까지 포함해야 운영 중 진단이 가능해진다.

> **수치에는 근거 등급이 표시되어 있다.**
> A는 산술로 도출된 값, B는 출처가 있는 값(링크 표기), C는 근거 없이 정한 예시값이다.
> C로 표시된 값은 그대로 채택하지 말고 측정 후 팀이 확정한다.
> 등급 정의는 quality-attributes.md의 "판정 기준 수치의 성격"을 참고한다.

## 1. 왜 별도로 다루는가

장애 대응 능력은 코드 품질과 별개다.
아무리 잘 짠 코드도 운영 중에 "지금 왜 느린가"에 답하지 못하면 복구가 늦어진다.
MTTR(평균 복구 시간)은 코드 품질이 아니라 관측 가능성이 결정한다.

기준은 단순하다. **새로 발생한 문제를 코드 배포 없이 진단할 수 있는가.**
문제가 생길 때마다 로그를 추가해서 재배포해야 한다면 관측 가능성이 부족한 것이다.

## 2. 세 기둥

| 축 | 답하는 질문 | 대표 도구 |
|----|-------------|-----------|
| 로그 | 무슨 일이 있었는가 | 구조화 로그, 로그 수집기 |
| 메트릭 | 얼마나 자주, 얼마나 심한가 | Micrometer, Prometheus |
| 추적 | 어느 구간에서 시간이 새는가 | OpenTelemetry, APM |

셋 중 하나만으로는 부족하다.
메트릭은 이상을 알려 주지만 원인을 말해 주지 않고, 로그는 원인을 담고 있지만 전체 규모를 보여 주지 못한다.

## 3. 로그

점검 항목
* `[인프라]` `OBS-3-01` 구조화된 형식(JSON)으로 남는가
* `[코드]` `OBS-3-02` 요청 단위 상관관계 ID가 모든 로그에 붙는가
* `[코드]` `OBS-3-03` 로그 레벨이 의미에 맞게 쓰이는가
* `[코드]` `OBS-3-04` 개인정보와 인증 토큰이 남지 않는가
* `[설계]` `OBS-3-05` 로그가 성능과 비용에 영향을 줄 만큼 과도하지 않은가
* `[인프라]` `OBS-3-06` 보존 기간과 접근 권한이 정의되어 있는가

판정 기준 (전부 등급 C. 근거 없음)

| 항목 | 예시값 | 정한 이유 |
|------|--------|-----------|
| 요청당 INFO 로그 | 3줄 이하 | 상태 변화만 남긴다. 그 이상은 DEBUG로 |
| 단일 로그 길이 | 2KB 이하 | 응답 본문 전체를 찍지 않는다 |
| 로그로 인한 응답시간 증가 | p99의 5% 이하 | 초과 시 비동기 appender 검토 |
| 보존 기간 | 운영 로그 30일, 감사 로그 1년 | 조사 필요 기간과 비용의 절충 |

```java
// 점검 대상: 문자열 연결 로그. 검색과 집계가 불가능하다
log.info("요청 완료: " + requestId + ", 금액: " + amount);

// 개선: 구조화 필드로 남겨 검색과 집계가 가능하게 한다
log.info("request completed", kv("requestId", requestId), kv("amount", amount));
```

구조화 출력은 코드가 아니라 설정에서 켠다.

```xml
<!-- 개선: 운영 프로파일에서 JSON 출력과 비동기 appender를 쓴다 -->
<springProfile name="prod">
  <appender name="JSON" class="ch.qos.logback.core.ConsoleAppender">
    <encoder class="net.logstash.logback.encoder.LogstashEncoder">
      <includeMdcKeyName>traceId</includeMdcKeyName>
      <customFields>{"service":"${APP_NAME}","version":"${APP_VERSION}"}</customFields>
    </encoder>
  </appender>

  <appender name="ASYNC" class="ch.qos.logback.classic.AsyncAppender">
    <queueSize>2048</queueSize>
    <discardingThreshold>0</discardingThreshold>  <!-- 0이면 WARN 이상은 버리지 않음 -->
    <neverBlock>true</neverBlock>                  <!-- 큐가 차도 요청 스레드를 막지 않음 -->
    <appender-ref ref="JSON"/>
  </appender>

  <root level="INFO">
    <appender-ref ref="ASYNC"/>
  </root>
</springProfile>
```

`neverBlock`을 켜지 않으면 로그 수집이 느려질 때 요청 스레드가 함께 멈춘다.
관측을 위한 장치가 장애 원인이 되는 전형적인 사례다.

요청 단위로 로그를 묶으려면 상관관계 ID가 필요하다.

```java
public class TraceIdFilter extends OncePerRequestFilter {
    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain chain) throws Exception {
        String traceId = Optional.ofNullable(request.getHeader("X-Trace-Id"))
                                 .orElseGet(() -> UUID.randomUUID().toString());
        MDC.put("traceId", traceId);
        try {
            chain.doFilter(request, response);
        } finally {
            MDC.clear();   // 스레드풀 재사용이므로 반드시 정리한다
        }
    }
}
```

`MDC.clear()`를 빠뜨리면 다음 요청이 이전 요청의 traceId를 이어받아 로그가 뒤섞인다.
비동기 실행에서는 MDC가 자동으로 전파되지 않으므로 별도 처리가 필요하다.

로그 레벨 기준을 정해 둔다.

| 레벨 | 기준 | 알림 |
|------|------|------|
| ERROR | 사람이 개입해야 하는 실패 | 즉시 |
| WARN | 자동 복구됐지만 반복되면 문제인 상황 | 임계치 초과 시 |
| INFO | 상태 변화 기록. 생성, 완료, 취소 등 | 없음 |
| DEBUG | 개발과 조사용. 운영에서는 기본 비활성 | 없음 |

모든 예외를 ERROR로 남기면 알림이 무의미해진다.
사용자 입력 오류(400)는 WARN 이하가 맞다.

## 4. 메트릭

점검 항목
* `[인프라]` `OBS-4-01` RED 또는 USE 관점의 기본 지표를 노출하는가
* `[코드]` `OBS-4-02` 기술 지표뿐 아니라 비즈니스 지표(핵심 요청 처리 건수, 외부 연동 실패율)를 함께 수집하는가
* `[코드]` `OBS-4-03` 태그(label) 카디널리티가 폭발하지 않는가
* `[인프라]` `OBS-4-04` 수집 주기와 보존 기간이 정의되어 있는가

| 관점 | 지표 | 대상 |
|------|------|------|
| RED | Rate, Errors, Duration | 요청 처리 서비스 |
| USE | Utilization, Saturation, Errors | 자원(CPU, 커넥션풀, 큐) |

판정 기준 (전부 등급 C. 근거 없음)

| 항목 | 예시값 | 정한 이유 |
|------|--------|-----------|
| 메트릭 하나당 시계열 수 | 1000개 이하 | 태그 조합의 곱으로 늘어난다 |
| 태그 값 종류 | 항목당 50개 이하 | ID, 이메일, URL 원문은 태그 금지 |
| 수집 주기 | 15초 | 급변 감지와 저장 비용의 절충 |
| 보존 기간 | 원본 15일, 다운샘플링 후 1년 | 추세 비교에 필요한 기간 |

```java
// 개선: 기술 지표가 아니라 비즈니스 실패를 메트릭으로 노출한다
private final Counter failures;

public ExternalRequestService(MeterRegistry registry) {
    this.failures = Counter.builder("external.request.failures")
        .tag("provider", "primary")     // 값 종류가 제한된 것만 태그로
        .register(registry);
}
```

```java
// 점검 대상: 태그에 사용자 ID를 넣으면 시계열이 무한히 늘어나 수집기가 죽는다
Counter.builder("request.created").tag("userId", userId.toString());
```

카디널리티 사고를 코드 리뷰에만 의존하지 말고 설정으로도 막는다.

```yaml
# 개선: URI 태그 상한을 두고, 초과 시 알 수 있게 한다
management:
  metrics:
    tags:
      application: ${APP_NAME}
      version: ${APP_VERSION}
    web:
      server:
        max-uri-tags: 100     # 초과 시 경고 로그가 남는다
    distribution:
      percentiles-histogram:
        http.server.requests: true
      slo:
        http.server.requests: 100ms, 300ms, 1s
```

기술 지표만으로는 부족하다.
CPU와 응답시간이 정상인데 핵심 기능이 전부 실패하고 있을 수 있다.
비즈니스 지표가 최종 안전망이다.

## 5. 분산 추적

점검 항목
* `[인프라]` `OBS-5-01` 서비스 간 호출에 추적 컨텍스트가 전파되는가
* `[인프라]` `OBS-5-02` DB 쿼리와 외부 호출이 스팬으로 기록되는가
* `[인프라]` `OBS-5-03` 샘플링 정책이 정의되어 있는가
* `[코드]` `OBS-5-04` 비동기 실행에서 추적 컨텍스트가 끊기지 않는가

한 요청이 여러 서비스와 DB를 거칠 때, 어느 구간이 느린지는 추적 없이 알 수 없다.
전체 응답 2초 중 1.8초가 특정 외부 연동 호출이었다는 사실은 스팬 단위로 봐야 드러난다.

판정 기준 (등급 C. 근거 없음)

| 대상 | 샘플링 비율 | 근거 |
|------|-------------|------|
| 오류 응답 | 100% | 조사 대상은 빠짐없이 남긴다 |
| 느린 요청 (p99 초과) | 100% | 성능 문제의 근거 자료 |
| 핵심 거래 경로 | 10% | 정상 흐름의 기준선 확보 |
| 일반 조회 | 1% | 비용 통제 |

```yaml
# 개선: 기본 비율을 낮게 두고, 오류와 지연은 별도로 전량 수집한다
management:
  tracing:
    sampling:
      probability: 0.01
  otlp:
    tracing:
      endpoint: http://collector:4318/v1/traces
```

샘플링은 비용과 진단력의 절충이다.
전량 수집은 저장 비용이 급증하고, 너무 낮추면 정작 필요한 요청이 남지 않는다.

## 6. SLO와 알림

측정만 하고 목표가 없으면 숫자를 봐도 판단할 수 없다.

점검 항목
* `[설계]` `OBS-6-01` 주요 기능에 SLI와 SLO가 숫자로 정의되어 있는가
* `[인프라]` `OBS-6-02` 알림이 원인이 아니라 증상(사용자 영향) 기준인가
* `[프로세스]` `OBS-6-03` 알림에 대응 절차가 연결되어 있는가
* `[프로세스]` `OBS-6-04` 무시되는 알림이 쌓이고 있지 않은가

SLO 예시: `핵심 조회 API는 p99 200ms 이하 응답을 30일 기준 99.9% 충족한다`

판정 기준

경보 임계는 Google SRE Workbook의 다중 구간 소진율 기준을 따른다 (등급 B).
출처: https://sre.google/workbook/alerting-on-slos/

| 소진 속도 | 관측 구간(긴 구간) | 함께 볼 짧은 구간 | 30일 예산 기준 의미 | 대응 |
|-----------|--------------------|-------------------|---------------------|------|
| 14.4배 | 1시간 | 5분 | 1시간에 2% 소진 | 즉시 호출(page) |
| 6배 | 6시간 | 30분 | 6시간에 5% 소진 | 즉시 호출(page) |
| 1배 | 3일 | 6시간 | 3일에 10% 소진 | 티켓 |

짧은 구간은 긴 구간의 12분의 1로 잡는 것이 출처의 권고이며, 두 구간이 동시에 임계를 넘을 때만 발화시켜 일시적 스파이크로 인한 오탐을 줄인다.
출처는 또한 요청량이 적은 서비스에서는 이 방식이 과민하게 동작한다고 지적한다. 시간당 10건 규모라면 실패 1건만으로도 매우 높은 소진율이 계산되므로, 저트래픽 서비스는 별도 방식이 필요하다.

아래는 근거 없는 예시값이다 (등급 C).

| 항목 | 예시값 | 조치 |
|------|--------|------|
| 알림 정확도 | 70% 이상 | 미달 시 임계치 재조정 |
| 주간 알림 건수 | 담당자당 10건 이하 | 초과 시 통합하거나 임계치 상향 |
| 미대응 알림 비율 | 10% 이하 | 초과한 알림은 삭제 대상 |

알림은 사용자 영향 기준으로 건다.

```yaml
# 개선: 자원 지표가 아니라 사용자 영향과 예산 소진 속도로 경보한다
groups:
  - name: core-api-slo
    rules:
      - alert: CoreApiErrorBudgetBurn
        expr: |
          (
            sum(rate(http_server_requests_seconds_count{uri="/v1/requests",status=~"5.."}[5m]))
            /
            sum(rate(http_server_requests_seconds_count{uri="/v1/requests"}[5m]))
          ) > 0.005
        for: 10m
        labels:
          severity: page
        annotations:
          summary: "핵심 API 오류율이 SLO 임계를 초과"
          runbook: "https://wiki.example.com/runbook/core-api-error"
```

"CPU 80% 초과"는 사용자에게 아무 문제가 없을 수도 있고, "핵심 API 오류율 5% 초과"는 확실한 문제다.
전자로 알림을 걸면 대응할 필요 없는 호출이 쌓여 결국 아무도 알림을 보지 않게 된다.

`runbook` 링크가 없는 알림은 만들지 않는다.
받은 사람이 무엇을 해야 할지 모르는 알림은 소음이다.
런북 한 건의 구성과 갱신 방법은 [qa-incident-response-rationale.md](./qa-incident-response-rationale.md) 8장을 참고한다.

### 알림 정기 점검 절차

```
분기 1회 수행

1. 지난 분기 발생한 알림 전수 집계
2. 알림별로 다음을 판정
   - 실제 조치가 필요했는가 (Y/N)
   - 대응까지 걸린 시간
   - runbook이 실제로 도움이 됐는가
3. 조치가 필요 없었던 비율이 30%를 넘는 알림 -> 임계치 상향 또는 삭제
4. 한 번도 발화하지 않은 알림 -> 조건이 잘못됐는지 확인
5. 장애는 있었는데 알림이 없었던 구간 -> 새 알림 추가
6. 결과와 변경 내역 기록
```

알림 목록은 늘어나기만 하고 줄지 않는 경향이 있다.
정기적으로 줄이는 절차가 없으면 몇 년 뒤에는 아무도 보지 않는 목록이 된다.

## 7. 진단 가능성 설계

점검 항목
* `[코드]` `OBS-7-01` 예외에 원인 추적에 필요한 식별자가 포함되는가
* `[코드]` `OBS-7-02` 외부 시스템 응답 코드가 원문 그대로 기록되는가
* `[인프라]` `OBS-7-03` 배포 버전이 로그와 메트릭에 태그로 남는가

```java
// 점검 대상: 무엇이 실패했는지 알 수 없다
throw new IllegalStateException("요청 처리 실패");

// 개선: 조사에 필요한 맥락을 담는다
throw new RequestProcessingException(
    "요청 처리 실패 requestId=%d, step=%s".formatted(requestId, step), cause);
```

배포 버전 태그가 없으면 "이번 배포 이후 느려졌는가"에 답할 수 없다.

## 8. 측정 지표

| 지표 | 의미 | 목표 (예시값) |
|------|------|---------------|
| MTTD | 장애 발생부터 인지까지 걸린 시간 | 5분 이하 |
| MTTR | 인지부터 복구까지 걸린 시간 | RTO 이내 |
| 알림 정확도 | 실제 조치가 필요했던 알림 비율 | 70% 이상 |
| 무계측 구간 비율 | 메트릭이나 추적이 없는 코드 경로 | 핵심 경로 0% |
| 코드 변경 없이 진단된 장애 비율 | 관측 가능성의 실효성 | 80% 이상 |

## 9. 관련 문서

* 코드 수준 분석성: [qa-maintainability-rationale.md](./qa-maintainability-rationale.md)
* 가용성 목표와 에러 예산: [qa-reliability-rationale.md](./qa-reliability-rationale.md)
* 목표 수치 설정: [qa-tradeoffs-rationale.md](./qa-tradeoffs-rationale.md)
* 로그의 민감 정보: [qa-security-rationale.md](./qa-security-rationale.md)
* 경보 이후의 대응 절차: [qa-incident-response-rationale.md](./qa-incident-response-rationale.md)

## 10. 참고 문헌

| 항목 | 링크 |
|------|------|
| Google SRE Workbook, Alerting on SLOs | https://sre.google/workbook/alerting-on-slos/ |
| Grafana, 다중 구간 소진율 경보 구현 예 | https://grafana.com/blog/how-to-implement-multi-window-multi-burn-rate-alerts-with-grafana-cloud/ |
