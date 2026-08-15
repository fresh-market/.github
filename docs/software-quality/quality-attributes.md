# 백엔드 소프트웨어 품질 속성

이 디렉터리는 백엔드 개발에서 고려해야 할 품질 속성(비기능 요구사항)을 정리한다.
이 문서(quality-attributes.md)는 진입점 역할을 하며, 표준 모델과의 매핑과 각 속성 문서로의 링크를 담는다.

대상 기술 스택은 Java, Spring, MySQL 8.4를 기준으로 한다.
특정 서비스나 도메인에 종속되지 않는 공통 백엔드 문서이며, 예시는 아래 범용 어휘로 표기한다.

## 예시에 쓰는 범용 어휘

문서의 코드와 SQL 예시는 특정 업종의 용어 대신 다음 어휘를 사용한다.
읽을 때는 각자의 도메인 개념으로 바꿔 읽으면 된다.

| 예시 어휘 | 뜻 | 각 도메인에서의 예 |
|-----------|-----|--------------------|
| 한정 자원 (`resource_allocation`, `remaining_qty`) | 동시에 여러 요청이 줄여 나가는 유한한 수량 | 재고, 좌석, 쿠폰 발급 수, API 크레딧, 계좌 잔액 |
| 요청 (`request`, `Record`) | 사용자가 만들어 상태가 변해 가는 주 엔티티 | 주문, 예약, 신청서, 티켓, 작업 |
| 외부 연동 (`external_request`, `ExternalProvider`) | 우리 트랜잭션 밖에 있는 시스템 | 결제사, 인증 기관, 알림 발송, 배송사, 타 팀 서비스 |
| 사용자 (`app_user`, `UserPrincipal`) | 인증 주체 | 회원, 직원, 클라이언트 애플리케이션 |

예시가 추상적이면 이해가 어렵고 지나치게 구체적이면 다른 도메인에서 쓸 수 없다.
그 절충으로 "한정 자원의 동시 차감"과 "외부 연동이 걸린 상태 전이" 두 가지를 대표 사례로 삼았다.
이 둘이 백엔드에서 정합성과 신뢰성 문제가 가장 자주 발생하는 구조이기 때문이다.

### 도메인에 맞게 채워야 하는 부분

다음 항목은 문서가 유형만 제시하고 구체적인 내용은 비워 두었다. 도입 시 채운다.

| 항목 | 위치 |
|------|------|
| 가용성 등급별 실제 기능 목록 | 신뢰성 1장 |
| 정합성 검사 항목의 구체적 대상 | 데이터 정합성 7장 |
| 데이터 등급별 실제 컬럼 분류 | 보안 4장 |
| 심각도 등급의 판정 기준 | 인시던트 대응 1장 |
| 서비스의 핵심 불변식 | 데이터 정합성 7장 |

## 이 문서가 다루는 것

기능 요구사항이 "무엇을 하는가"라면, 품질 속성은 "얼마나 잘 하는가"를 규정한다.
요청을 받아 저장하는 기능 자체는 어렵지 않지만, 초당 3000건을 200ms 안에 처리하면서, 동시 요청에서 수량이 어긋나지 않게 하고, 6개월 뒤에도 안전하게 고칠 수 있게 만드는 것이 어렵다.
장애와 재작성 비용의 대부분은 기능이 아니라 이 영역에서 발생한다.

기준 모델은 ISO/IEC 25010:2023 제품 품질 모델이다.
2023년 개정판은 9개 특성과 하위 특성으로 구성되며, 2011년판 대비 다음이 바뀌었다.

* 안전성(safety)이 특성으로 추가되었다.
* 사용성(usability)이 상호작용 능력(interaction capability)으로 대체되었다.
* 이식성(portability)이 유연성(flexibility)으로 대체되었다.
* 확장성(scalability)이 유연성의 하위 특성으로, 저항성(resistance)이 보안의 하위 특성으로 추가되었다.

## 문서 구성

| 품질 속성 | 문서 | 백엔드 체감 비중 |
|-----------|------|------------------|
| 기능 적합성 | [qa-functional-suitability-rationale.md](./qa-functional-suitability-rationale.md) | 높음 |
| 성능 효율성 | [qa-performance-efficiency-rationale.md](./qa-performance-efficiency-rationale.md) | 매우 높음 |
| 신뢰성 | [qa-reliability-rationale.md](./qa-reliability-rationale.md) | 매우 높음 |
| 보안 | [qa-security-rationale.md](./qa-security-rationale.md) | 매우 높음 |
| 유지보수성 | [qa-maintainability-rationale.md](./qa-maintainability-rationale.md) | 매우 높음 |
| 유연성과 확장성 | [qa-flexibility-rationale.md](./qa-flexibility-rationale.md) | 높음 |
| 호환성 | [qa-compatibility-rationale.md](./qa-compatibility-rationale.md) | 높음 |
| 데이터 정합성 | [qa-data-integrity-rationale.md](./qa-data-integrity-rationale.md) | 매우 높음 |
| 관측 가능성 | [qa-observability-rationale.md](./qa-observability-rationale.md) | 높음 |
| 인시던트 대응과 복구 | [qa-incident-response-rationale.md](./qa-incident-response-rationale.md) | 매우 높음 |
| 속성 간 트레이드오프 | [qa-tradeoffs-rationale.md](./qa-tradeoffs-rationale.md) | 설계 판단 기준 |
| LLM 기반 품질 검증 설계 | [qa-llm-verification.md](./qa-llm-verification.md) | 검증 자동화 |
| 미결정 값 | [pending-decisions.md](./pending-decisions.md) | 근거 없는 예시값 목록 |
| 검증 실행 방법과 워크 플로우 | [fresh-market/fm-backend 의 docs/verification/](https://github.com/fresh-market/fm-backend/blob/main/docs/verification/verification-guide.md) | 사용 설명 |

### 별도 문서를 두지 않은 특성

* **상호작용 능력(interaction capability)**: 서버 사이드 렌더링이 없는 API 서버에서는 최종 사용자 UI가 아니라 API 소비자(클라이언트 개발자)의 사용성 문제로 나타난다. 리소스 명명, 오류 메시지, 문서화 형태로 [qa-compatibility-rationale.md](./qa-compatibility-rationale.md)에서 다룬다.
* **안전성(safety)**: 인명이나 물리적 위해와 직결되는 도메인(의료 기기, 차량 제어 등)에서 독립 특성으로 다룬다. 커머스 백엔드에서는 금전 사고 방지가 이에 대응하며, 데이터 정합성과 보안 문서로 흡수했다.

## 인시던트 대응을 별도로 둔 이유

ISO 25010의 복구성(recoverability)은 시스템이 **복구 가능한 성질을 갖추었는가**를 다루지, 사람이 복구를 어떻게 수행하는가를 다루지 않는다.
그래서 RPO와 RTO를 정하는 것은 신뢰성 문서에 들어가지만, 그 RTO 안에 실제로 복구해 내는 절차는 어디에도 들어가지 않는다.

또한 장애 한복판에서 읽는 문서는 설계 검토용 문서와 형식이 완전히 달라야 한다.
짧고, 순서대로 실행 가능하고, 되돌릴 수 없는 조작이 표시되어 있어야 한다.
성격이 다른 문서를 속성 문서에 끼워 넣으면 둘 다 쓸모가 떨어진다.

## 데이터 정합성과 관측 가능성을 별도로 둔 이유

두 항목은 ISO 25010에 독립 특성으로 존재하지 않는다.
데이터 정합성은 보안의 무결성 하위 특성에 일부 걸치고, 관측 가능성은 유지보수성의 분석성에 일부 걸친다.
그러나 백엔드에서는 이 둘이 장애 발생 빈도와 대응 능력을 직접 좌우하므로, 하위 항목으로 묻어 두면 설계 단계에서 누락되기 쉽다.
표준 준수보다 실무 누락 방지를 우선해 독립 문서로 분리했다.

## 이 문서군의 사용 시점

품질 속성은 코드 한 줄을 보고 판단하기 어렵고 시스템 구성 단위에서 결정된다.
따라서 이 문서군은 코드 리뷰의 지적 기준이 아니라, 다음 시점의 검토 기준으로 쓴다.

1. 신규 기능 설계 시 목표 수치(지연시간, 가용성, 정합성 수준)를 정할 때
2. 아키텍처 결정 기록(ADR)에서 대안을 비교할 때
3. 장애 사후 분석에서 어느 속성이 부족했는지 진단할 때
4. 부하 증가나 요구 변경으로 기존 설계를 재검토할 때

각 문서의 "점검 항목"은 설계 검토 체크리스트로, "측정 지표"는 목표 수치를 정하고 검증하는 근거로 사용한다.

## 점검 항목 레벨 표기

항목마다 어느 층위에서 판정하는지를 접두어로 표시한다.
층위가 다르면 보는 사람과 보는 시점이 다르므로, 한 목록에 섞인 채로 두면 전부 코드 리뷰 항목처럼 오해된다.

| 표기 | 판정 대상 | 확인 시점 | 판정 주체 |
|------|-----------|-----------|-----------|
| `[코드]` | 소스 코드 변경분 | PR 리뷰 | 리뷰어 |
| `[설계]` | 구조와 계약, 데이터 모델 | 설계 리뷰, ADR 작성 | 설계자와 팀 |
| `[인프라]` | 설정, 배포, 실행 환경 | 인프라 변경, 배포 준비 | 개발자와 운영 담당 |
| `[프로세스]` | 정기 점검과 대응 절차 | 분기 점검, 사후 분석 | 팀 전체 |

**층위는 판정 대상이 무엇인지를 말하는 것이지, PR 에서 보는지 아닌지를 말하는 것이 아니다.**

PR 에서 무엇을 판정할지는 `fresh-market/fm-backend` 의 `.github/llm-verify/anchors.yml` 이 정한다.
바꾼 파일이 규칙을 트리거하고, 규칙의 `levels` 가 어느 층위를 켤지 정한다.
대부분의 규칙이 `[코드]`, `[설계]`, `[인프라]` 를 함께 켠다.
마이그레이션 파일 하나로 데이터 모델 결정(`[설계]`)을 판정할 수 있고,
`application.yml` 하나로 설정(`[인프라]`)을 판정할 수 있기 때문이다.

`[프로세스]` 만 어떤 규칙도 켜지 않는다. 기록을 봐야 하므로 G-AUDIT 이 주기별로 확인한다.

층위를 붙일 때는 **판정 대상이 어느 산출물인가**로 정한다.

```
소스 코드            [코드]
DDL, 스키마, 계약     [설계]
yml, 배포, 실행 환경  [인프라]
절차와 기록          [프로세스]
```

## 판정 기준 수치의 성격

각 문서에 나오는 임계치와 설정값은 **대부분 예시값이다.**
근거 없이 "적당히"라고 두면 판정이 사람마다 달라지므로 구체적인 숫자를 적어 두었을 뿐, 검증된 권장값이 아니다.

수치는 근거에 따라 세 등급으로 나뉜다.

| 등급 | 성격 | 신뢰도 | 예 |
|------|------|--------|-----|
| A | 산술로 도출되는 값 | 그대로 사용 가능 | 가용성별 다운타임, 리틀의 법칙 계산 |
| B | 도구 기본값 또는 공식 문서의 권장 | 근거는 있으나 문서에서 변형했을 수 있음 | MySQL과 커넥션풀 기본값, 라이브러리 기본 설정 |
| C | 실무 관행을 참고해 임의로 정한 값 | **근거 없음. 반드시 팀이 확정해야 함** | 로그 줄 수, 알림 정확도, 충돌률 구간, 검사 주기 |

각 수치 옆에 등급을 표시했고, B등급에는 출처 링크를 함께 적었다.
등급 표시가 없는 표는 전체가 C로 간주한다.

### 등급 B로 출처를 확인한 항목

| 항목 | 출처 | 해당 문서 |
|------|------|-----------|
| 커넥션풀 산정식 | HikariCP About Pool Sizing | 성능 효율성 |
| 에러 예산 소진율 경보 임계(14.4배 등) | Google SRE Workbook | 신뢰성, 관측 가능성 |
| 재시도 지터 방식(Full, Equal, Decorrelated) | AWS Architecture Blog | 신뢰성 |
| 서킷 브레이커 기본값 | Resilience4j 공식 문서 | 신뢰성 |
| 비밀번호 해시 파라미터 | OWASP Password Storage Cheat Sheet | 보안 |
| MySQL 타임아웃과 잠금 기본값 | MySQL 8.4 Reference Manual | 신뢰성, 정합성, 성능 |
| 변경 리드타임과 변경 실패율 | DORA State of DevOps Report | 유지보수성 |
| API 호환성과 오류 구조 | Google AIP | 호환성 |

### 등급 B에서 주의할 점

도구 기본값을 근거로 제시하더라도, 문서에 적힌 값이 기본값 그대로가 아닐 수 있다.
아래는 문서에서 기본값과 다르게 제시한 대표적인 항목이다.

| 항목 | 도구 기본값 | 문서에 적힌 값 | 변경 사유 |
|------|-------------|----------------|-----------|
| MySQL `innodb_lock_wait_timeout` | 50초 | 5초 | API 응답 예산 안에서 실패를 드러내기 위함 |
| MySQL `long_query_time` | 10초 | 1초 | 개선 대상을 더 넓게 잡기 위함 |
| 서킷 브레이커 최소 호출 수 | 100건 | 20건 | 트래픽이 적은 연동에서도 동작하게 하기 위함 |
| 서킷 브레이커 차단 유지 | 60초 | 30초 | 회복 확인을 더 자주 하기 위함 |

변경 사유가 그 서비스에 맞지 않으면 기본값을 쓰는 편이 낫다.

### 수치를 확정하는 순서

1. **A는 그대로 쓴다.** 계산 결과이므로 논의 대상이 아니다.
2. **B는 기본값과 문서 값을 비교하고 하나를 고른다.** 변경 사유가 납득되면 문서 값을, 아니면 기본값을 쓴다.
3. **C는 측정 후 정한다.** 현재 실제 값을 2주 이상 관측한 뒤, 그 분포를 근거로 임계를 잡는다. 측정 전에는 "경보 없이 관측만" 상태로 둔다.
4. 확정한 값과 근거를 기록한다. 기록이 없으면 다음 사람이 다시 임의값으로 되돌린다.

### 기준을 조정할 때

1. 조정한 값과 이유를 기록한다.
2. 기준을 완화할 때는 완화해도 안전한 근거(측정 데이터)를 함께 남긴다.
3. 기준을 계속 넘기는데 조정도 대응도 하지 않는 항목은 목록에서 뺀다. 지켜지지 않는 기준은 나머지 기준의 신뢰도까지 떨어뜨린다.

## 참고 문헌

| 항목 | 링크 |
|------|------|
| ISO/IEC 25010:2023 Product quality model | https://www.iso.org/standard/78176.html |
| ISO/IEC 25010:2023 온라인 브라우징(개정 요약) | https://www.iso.org/obp/ui/en/#!iso:std:78176:en |
| arc42 품질 모델(특성별 정리) | https://quality.arc42.org/standards/iso-25010 |
| 비기능 요구사항 작성 가이드 | https://www.workingsoftware.dev/the-ultimate-guide-to-write-non-functional-requirements/ |

### 수치 근거로 사용한 출처

| 항목 | 링크 |
|------|------|
| Google SRE Workbook, Alerting on SLOs | https://sre.google/workbook/alerting-on-slos/ |
| AWS Architecture Blog, Exponential Backoff And Jitter | https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/ |
| HikariCP, About Pool Sizing | https://github.com/brettwooldridge/HikariCP/wiki/About-Pool-Sizing |
| Resilience4j, CircuitBreaker | https://resilience4j.readme.io/docs/circuitbreaker |
| OWASP, Password Storage Cheat Sheet | https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html |
| MySQL 8.4 Reference Manual, InnoDB 시스템 변수 | https://dev.mysql.com/doc/refman/8.4/en/innodb-parameters.html |
| MySQL 8.4 Reference Manual, InnoDB 오류 처리 | https://dev.mysql.com/doc/refman/8.4/en/innodb-error-handling.html |
| DORA, State of DevOps Report | https://dora.dev/research/ |
| Google AIP 색인 | https://google.aip.dev/general |
