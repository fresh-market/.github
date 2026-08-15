# 유연성과 확장성 점검 항목의 근거

판정용 항목 목록은 [qa-flexibility-guideline.md](./qa-flexibility-guideline.md) 에 있다.
이 문서는 왜 그 기준인지와 예시를 담는다.

요구, 환경, 사용 맥락의 변화에 적응할 수 있는 정도를 뜻한다.
ISO/IEC 25010:2023에서 기존 이식성(portability)을 대체한 특성이다.

하위 특성
* **적응성(adaptability)**: 다른 환경으로 옮길 수 있는 정도
* **확장성(scalability)**: 부하 증가에 대응해 자원을 늘려 처리할 수 있는 정도 (2023년판 추가)
* **설치성(installability)**: 설치와 제거의 용이성
* **대체성(replaceability)**: 다른 구현으로 교체 가능한 정도

> **수치에는 근거 등급이 표시되어 있다.**
> A는 산술로 도출된 값, B는 출처가 있는 값(링크 표기), C는 근거 없이 정한 예시값이다.
> C로 표시된 값은 그대로 채택하지 말고 측정 후 팀이 확정한다.
> 등급 정의는 quality-attributes.md의 "판정 기준 수치의 성격"을 참고한다.

## 1. 확장성의 전제는 무상태다

인스턴스가 상태를 들고 있으면 수평 확장이 불가능해진다.
Spring 빈은 기본이 싱글톤이므로 인스턴스 필드에 가변 상태를 두면 요청 스레드끼리 그 값을 공유한다.

점검 항목
* `[코드]` `FLX-1-01` 싱글톤 빈에 가변 인스턴스 필드를 두지 않았는가
* `[코드]` `FLX-1-02` 상태가 필요하면 지역 변수나 파라미터로 처리하는가
* `[인프라]` `FLX-1-03` 세션과 캐시를 인메모리가 아니라 외부 저장소에 두는가
* `[인프라]` `FLX-1-04` 업로드 파일을 로컬 디스크가 아니라 공유 스토리지에 두는가

```java
// 점검 대상: 싱글톤 빈의 가변 필드. 요청끼리 값이 섞인다
@Service
public class InvoiceService {
    private Long currentUserId;

    public Invoice issue(Long userId) {
        this.currentUserId = userId;              // (1) A가 저장
        applyDiscount();                          // (2) 그사이 B가 (1)을 덮어씀
        return new Invoice(this.currentUserId);   // (3) A의 청구서에 B의 id
    }
}

// 개선: 상태를 지역 변수로 -> 스레드마다 독립
@Service
public class InvoiceService {
    public Invoice issue(Long userId) {
        Invoice invoice = new Invoice(userId);
        applyDiscount(invoice);
        return invoice;
    }
}
```

이런 버그는 동시 요청이 겹칠 때만 드물게 나타나 재현과 추적이 매우 어렵다.
서버 1대에서는 보이지 않다가 증설 후 터지는 전형적인 사례다.

세션과 파일 저장은 코드가 아니라 구성에서 결정된다.

```yaml
# 개선: 세션을 외부 저장소로 옮겨 인스턴스 교체와 증설에 영향을 받지 않게 한다
spring:
  session:
    store-type: redis
    timeout: 30m
    redis:
      namespace: ${APP_NAME}:session
  data:
    redis:
      host: ${REDIS_HOST}
      lettuce:
        pool:
          max-active: 16
```

판정 기준 (등급 C. 근거 없음)

| 항목 | 기준 | 확인 방법 |
|------|------|-----------|
| 인스턴스 상태 보유 | 0 | 임의 인스턴스를 죽여도 진행 중 세션이 유지되는가 |
| 로컬 디스크 의존 | 임시 파일 외 0 | 컨테이너 재시작 후 기능 정상 여부 |
| 인스턴스 교체 영향 | 사용자 체감 없음 | 롤링 배포 중 오류율 변화 |

## 2. 다중 인스턴스에서 깨지는 것들

단일 인스턴스 가정으로 짠 코드는 증설하는 순간 중복 실행된다.

점검 항목
* `[인프라]` `FLX-2-01` 스케줄러가 다중 인스턴스에서 중복 실행되지 않도록 막았는가
* `[코드]` `FLX-2-02` 인메모리 락으로 동시성을 제어하고 있지 않은가
* `[코드]` `FLX-2-03` 인메모리 캐시의 무효화가 전 인스턴스에 전파되는가

```java
// 점검 대상: 3대 운영 시 같은 시각에 3번 실행되어 같은 작업이 세 번 일어난다
@Scheduled(cron = "0 0 * * * *")
public void runBatch() { ... }
```

```java
// 점검 대상: synchronized는 한 JVM 안에서만 유효 -> 인스턴스 간 경합은 못 막는다
public synchronized void decrease(Long resourceId, int qty) { ... }
```

인스턴스 간 정합성은 언어 수준 락이 아니라 DB 락이나 분산 락으로 해결한다.

```sql
-- 개선: DB 기반 분산 락 테이블. 인스턴스 하나만 작업을 가져간다
CREATE TABLE scheduler_lock (
    task_name   VARCHAR(100) NOT NULL PRIMARY KEY,
    locked_by   VARCHAR(100) NOT NULL,
    locked_at   DATETIME(3)  NOT NULL,
    lock_until  DATETIME(3)  NOT NULL
);

-- 획득 시도: 만료된 락만 가져갈 수 있다
UPDATE scheduler_lock
SET locked_by = ?, locked_at = NOW(3), lock_until = NOW(3) + INTERVAL ? SECOND
WHERE task_name = ? AND lock_until < NOW(3);
-- 영향 행 수가 1이면 획득 성공, 0이면 다른 인스턴스가 실행 중
```

판정 기준 (등급 C. 근거 없음)

| 항목 | 기준 | 근거 |
|------|------|------|
| 락 유지 시간 | 예상 작업 시간의 3배 | 지연되어도 중복 실행 방지 |
| 락 최대 유지 시간 | 30분 | 인스턴스 급사 시 무한 점유 방지 |
| 캐시 무효화 전파 지연 | 5초 이내 | 인스턴스 간 값 불일치 허용 한계 |
| 인메모리 캐시 대상 | 변경이 드문 데이터만 | 코드 테이블, 설정값 등 |

전파가 필요한 캐시를 인메모리로 두면 인스턴스마다 다른 값을 반환한다.
사용자가 새로고침할 때마다 결과가 달라지는 현상이 여기서 나온다.

## 3. 확장의 단계 전략

처음부터 대규모를 가정하고 만들면, 존재하지 않는 병목을 위해 실재하는 버그 위험을 떠안게 된다.
비정규화와 캐시는 "진실이 둘이 되어 어긋나는" 정확성 비용을 먼저 치른다.

| 단계 | 조치 | 도입 판정 기준 |
|------|------|----------------|
| 1 | 쿼리와 인덱스 최적화, N+1 제거 | 처음부터 |
| 2 | 무상태화, 애플리케이션 수평 확장 | CPU 사용률 평시 60% 초과 |
| 3 | 읽기 복제본 분리 | 읽기가 전체 쿼리의 80% 초과이고 DB CPU 60% 초과 |
| 4 | 캐시 계층 도입 | 동일 조회 반복률 70% 초과 |
| 5 | 비정규화, 집계 테이블 | 실시간 집계가 목표 p99를 넘김 |
| 6 | 샤딩, 서비스 분리 | 단일 DB 쓰기가 한계에 도달 |

각 단계는 앞 단계를 다 하고 넘어간다.
정확성이 필요한 경로와 근사가 허용되는 경로를 분리하는 것이 단계 4 이후의 핵심 원칙이다.

읽기 복제본을 도입하면 복제 지연이 생긴다.

```sql
-- 개선: 복제 지연을 상시 확인한다
SHOW REPLICA STATUS;
-- Seconds_Behind_Source 가 임계를 넘으면 읽기를 소스로 전환하거나 경보한다
```

| 항목 | 기준 | 조치 |
|------|------|------|
| 복제 지연 | 1초 이하 | 3초 초과 시 경보 |
| 쓰기 직후 읽기 | 소스 DB로 라우팅 | 복제본에서 읽으면 방금 쓴 값이 안 보인다 |
| 복제본 대상 | 통계, 목록, 검색 | 금전 처리와 자원 차감 검증은 제외 |

## 4. 적응성과 대체성

점검 항목
* `[인프라]` `FLX-4-01` 환경별 차이가 코드가 아니라 설정으로 분리되어 있는가
* `[인프라]` `FLX-4-02` 설정과 비밀정보가 소스에 하드코딩되어 있지 않은가
* `[설계]` `FLX-4-03` 외부 의존이 추상화 뒤에 있어 교체 가능한가

```java
// 점검 대상: 특정 공급자 구현에 직접 의존 -> 공급자 교체 시 서비스 코드까지 바뀐다
@Service
public class RequestService {
    private final AcmeProviderClient providerClient;
}

// 개선: 도메인이 정의한 인터페이스에 의존
@Service
public class RequestService {
    private final ExternalProvider provider;
}
```

추상화는 교체 가능성이 실재할 때만 만든다.
아무도 쓰지 않을 확장점을 위해 지금의 가독성을 파는 것은 유연성이 아니라 낭비다.

판정 기준 (등급 C. 근거 없음)

| 상황 | 추상화 |
|------|--------|
| 구현이 2개 이상 동시 운영 | 필요 |
| 교체가 계획에 있음 | 필요 |
| 테스트에서 대역이 필요 | 필요 |
| 구현이 하나뿐이고 교체 계획 없음 | 불필요 |

```yaml
# 개선: 환경 차이는 프로파일로, 비밀은 환경변수로 분리한다
spring:
  config:
    activate:
      on-profile: prod
  datasource:
    url: jdbc:mysql://${DB_HOST}:3306/${DB_NAME}?useSSL=true
    username: ${DB_USER}
    password: ${DB_PASSWORD}    # 소스에 값을 두지 않는다
external:
  provider: ${EXTERNAL_PROVIDER:primary}
```

## 5. 스키마 변경의 유연성

배포와 스키마 변경이 동시에 일어나면 롤백이 불가능해진다.
컬럼 제거는 단계로 나눈다 (expand and contract).

> 이 절은 `qa-compatibility-rationale.md` 5장과 세 항목이 겹친다.
> 스키마는 계약이므로 호환성 문서가 같은 것을 다루기 때문이다.
> 지금은 `defers_to` 로 발화만 하나로 줄여 두었고, 두 장을 합치는 것은 남은 일이다.

점검 항목
* `[설계]` `FLX-5-01` 컬럼 제거를 4단계로 나눴는가
* `[인프라]` `FLX-5-02` 대용량 테이블 DDL이 온라인으로 수행 가능한지 확인했는가
* `[프로세스]` `FLX-5-03` 스키마 변경 후에도 이전 버전 코드로 롤백 가능한가

```
1. 새 컬럼 추가 (기존 코드는 무시)
2. 양쪽에 쓰기 (읽기는 아직 기존 컬럼)
3. 데이터 이관 후 읽기를 새 컬럼으로 전환
4. 기존 컬럼 제거
```

```sql
-- 개선: 잠금 없이 수행 가능한지 명시적으로 요구한다
ALTER TABLE record ADD COLUMN memo VARCHAR(200),
    ALGORITHM=INPLACE, LOCK=NONE;
```

이렇게 명시하면 온라인 수행이 불가능한 변경일 때 MySQL이 실행 대신 오류를 낸다.
모르고 테이블 전체를 잠그는 사고를 막을 수 있다.

| 항목 | 기준 |
|------|------|
| 온라인 DDL 필수 대상 | 행 수 100만 이상 테이블 |
| DDL 수행 시간대 | 트래픽 하위 20% 구간 |
| 롤백 가능 기간 | 스키마 변경 후 최소 1회 배포 주기 |

## 6. 측정 지표

| 지표 | 의미 | 목표 (예시값) |
|------|------|---------------|
| 확장 선형성 | 인스턴스 2배 증설 시 처리량 증가 비율 | 1.7배 이상 |
| 인스턴스 기동 시간 | 트래픽 급증 대응 속도 | 60초 이내 |
| 환경 추가 소요 시간 | 새 환경 구성에 걸리는 시간 | 1일 이내 |
| 설정 변경만으로 대응 가능한 요구 비율 | 배포 없이 바꿀 수 있는 범위 | 운영 파라미터 100% |
| 복제 지연 | 읽기 분리의 안전 여부 | 1초 이하 |

선형성이 1.7배에 못 미치면 어딘가에 공유 병목(DB, 락, 외부 연동)이 있다는 뜻이다.
증설을 계속하기 전에 그 병목을 먼저 찾는다.

## 7. 관련 문서

* 성능 개선 순서: [qa-performance-efficiency-rationale.md](./qa-performance-efficiency-rationale.md)
* 확장과 정합성의 충돌: [qa-tradeoffs-rationale.md](./qa-tradeoffs-rationale.md)
* 다중 인스턴스에서의 정합성: [qa-data-integrity-rationale.md](./qa-data-integrity-rationale.md)
