# 유지보수성 점검 항목의 근거

판정용 항목 목록은 [qa-maintainability-guideline.md](./qa-maintainability-guideline.md) 에 있다.
이 문서는 왜 그 기준인지와 예시를 담는다.

수정, 개선, 환경 변화 적응을 효과적이고 효율적으로 할 수 있는 정도를 뜻한다.

하위 특성
* **모듈성**: 한 부분의 변경이 다른 부분에 영향을 적게 주는 정도
* **재사용성**: 여러 곳에서 활용 가능한 정도
* **분석성**: 변경 영향과 결함 원인을 파악할 수 있는 정도
* **수정성**: 결함 없이 고칠 수 있는 정도
* **시험성(testability)**: 검증 기준을 세우고 시험할 수 있는 정도

장기 비용에 가장 크게 영향을 주는 속성이며, 다른 속성을 개선할 수 있는 **능력의 전제조건**이다.
유지보수 불가능한 코드는 성능 개선도 보안 패치도 못 한다.

이 문서는 `[코드]` 항목 비중이 가장 높다. 다만 판정을 사람의 인상에만 맡기지 않도록 자동화 가능한 기준을 함께 둔다.

> **수치에는 근거 등급이 표시되어 있다.**
> A는 산술로 도출된 값, B는 출처가 있는 값(링크 표기), C는 근거 없이 정한 예시값이다.
> C로 표시된 값은 그대로 채택하지 말고 측정 후 팀이 확정한다.
> 등급 정의는 quality-attributes.md의 "판정 기준 수치의 성격"을 참고한다.

## 1. 모듈성: 도메인 경계

도메인형 구조(package-by-feature)의 핵심은 각 도메인이 독립적으로 변경 가능한 단위라는 점이다.

> **이 절의 점검 항목은 backend 저장소가 소유한다.**
> 도메인 경계, 순환 의존, 내부 타입 교환의 판정 기준은 `docs/code-architecture/domain-package-boundary-guideline.md`에 있다.
> 그쪽이 패키지 구조와 ArchUnit 규칙까지 명시하고 있어 더 구체적이다. 이 문서는 배경과 자동화 방법만 남긴다.

```java
// 점검 대상: A 도메인이 B 도메인의 Repository에 직접 침투
@Service
public class RecordService {
    private final UserRepository userRepository;   // user 내부 구현에 의존
}

// 개선: B가 공개한 인터페이스로 협력
@Service
public class RecordService {
    private final UserQueryService userQueryService;   // user의 공개 API
}
```

Entity를 다른 도메인에 그대로 넘기면 받는 쪽이 그 Entity의 모든 필드와 연관에 의존하게 되어, 구조를 바꿀 수 없게 된다.

순환 참조는 특히 경계한다. 두 도메인이 서로를 참조하면 한쪽만 떼어 변경하거나 테스트할 수 없다.

### 구조 규칙을 테스트로 강제하기

리뷰에서 매번 사람이 잡는 대신 자동화한다.

```java
// ArchUnit으로 도메인 경계를 테스트로 고정
@Test
void 도메인은_다른_도메인의_내부에_접근하지_않는다() {
    ArchRule rule = noClasses()
        .that().resideInAPackage("..record..")
        .should().dependOnClassesThat()
        .resideInAPackage("..user.repository..");

    rule.check(new ClassFileImporter().importPackages("com.example.app"));
}

@Test
void 도메인_사이에_순환_참조가_없다() {
    slices().matching("com.example.app.(*)..")
        .should().beFreeOfCycles()
        .check(new ClassFileImporter().importPackages("com.example.app"));
}
```

판정 기준 (등급 C. 근거 없음)

| 항목 | 기준 |
|------|------|
| 도메인 간 순환 참조 | 0건 |
| 다른 도메인 내부 클래스 참조 | 0건 |
| 한 도메인이 의존하는 다른 도메인 수 | 3개 이하 |

## 2. 시험성: 테스트하기 어려우면 설계가 잘못된 것이다

점검 항목
* `[코드]` `MNT-2-01` Controller에 비즈니스 로직이 없는가
* `[코드]` `MNT-2-02` 외부 의존성이 구현체가 아니라 추상화에 의존하는가
* `[코드]` `MNT-2-03` 시간, 랜덤, 현재 사용자 같은 암묵적 의존이 주입 가능한가

테스트 실행 시간과 테스트 설계 자체의 품질(동작 검증, 테스트 더블, 격리)은 backend 저장소의 `unit-testing-guideline.md`가 소유한다.

```java
// 점검 대상: 현재 시각을 직접 호출 -> 만료 로직을 테스트할 수 없다
public boolean isExpired() {
    return LocalDateTime.now().isAfter(expiredAt);
}

// 개선: Clock을 주입해 시간을 통제 가능하게 만든다
public boolean isExpired(Clock clock) {
    return LocalDateTime.now(clock).isAfter(expiredAt);
}
```

Controller에 로직이 들어가면 HTTP 요청 없이는 그 로직을 테스트할 수 없고, 배치나 메시지 소비자에서 재사용할 수도 없다.

판정 기준 (등급 C. 근거 없음)

| 항목 | 기준 | 조치 |
|------|------|------|
| 단위 테스트 전체 실행 시간 | 1분 이내 | 초과 시 통합 테스트와 분리 |
| 단일 테스트 실행 시간 | 100ms 이내 | 초과는 통합 테스트로 분류 |
| 전체 빌드 시간 | 10분 이내 | 초과 시 병렬화 또는 분할 |
| 테스트 실패 재현율 | 100% | 간헐적 실패는 즉시 수정 대상 |

간헐적으로 실패하는 테스트(flaky test)는 하나만 있어도 전체 신뢰를 무너뜨린다.
고칠 수 없으면 비활성화하고 이슈를 남긴다. 방치가 가장 나쁘다.

### 좋은 테스트의 네 기둥

회귀 방어와 리팩터링 내성이 테스트의 **가치**를, 빠른 피드백과 유지보수성이 **비용**을 결정한다.
이 중 리팩터링 내성이 가장 먼저 지켜야 할 속성이다.

```java
// 점검 대상: 내부 호출을 검증 -> save를 saveAll로 바꾸면 깨짐 (거짓 경보)
recordService.create(command);
verify(recordRepository).save(any());

// 개선: 관찰 가능한 동작을 검증 -> 내부를 바꿔도 살아남음
Record result = recordService.create(command);
assertThat(result.getStatus()).isEqualTo(Status.CREATED);
```

거짓 경보가 반복되면 팀은 테스트 실패를 무시하기 시작하고, 결국 진짜 실패도 함께 묻힌다.
테스트를 신뢰할 수 없게 되는 순간 테스트의 가치는 사라진다.

## 3. 수정성: 변경 지점을 하나로 모은다

점검 항목
* `[코드]` `MNT-3-01` 같은 로직이 여러 곳에 복사되어 있지 않은가
* `[코드]` `MNT-3-02` 매직 넘버가 상수로 분리되어 있는가
* `[설계]` `MNT-3-03` 정책 변경 시 고쳐야 할 파일 수를 예측할 수 있는가

```java
// 점검 대상: 세 곳에 같은 계산이 복사 -> 비율 변경 시 한 곳을 빠뜨린다
int adjusted = origin - origin * 10 / 100;

// 개선: 상수와 단일 계산 지점
private static final int ADJUSTMENT_RATE_PERCENT = 10;
```

중복 제거는 줄 수를 줄이는 일이 아니라 변경 지점을 하나로 모으는 일이다.

판정 기준 (등급 C. 근거 없음. 검토를 유발하는 신호일 뿐이다)

| 항목 | 예시값 |
|------|--------|
| 중복 코드 비율 | 5% 이하 |
| 하나의 정책 변경이 건드리는 파일 수 | 3개 이하 |
| 메서드 길이 | 50줄 이하 |
| 클래스 길이 | 500줄 이하 |
| 메서드 파라미터 수 | 4개 이하 |

길이 기준은 절대 규칙이 아니라 검토 신호다.
넘었다고 무조건 나쁜 것이 아니라, 넘었으면 한 번 들여다보라는 뜻이다.

## 4. 분석성: 문제 원인을 찾을 수 있는가

점검 항목
* `[코드]` `MNT-4-01` 이름이 역할을 드러내는가
* `[코드]` `MNT-4-02` 주석이 "무엇을"이 아니라 "왜"를 설명하는가
* `[코드]` `MNT-4-03` 예외가 스택과 함께 남는가
* `[코드]` `MNT-4-04` 예외를 삼키지 않는가

```java
// 나쁜 주석: 코드가 이미 말하는 것을 반복
count++; // count를 1 증가시킨다

// 좋은 주석: 코드만으로 알 수 없는 이유를 설명
// 외부 공급자가 0.5초 내 중복 요청을 거부하므로 최소 간격을 둔다
Thread.sleep(500);
```

```java
// 점검 대상: 스택을 버려 발생 위치를 알 수 없음
catch (ExternalException e) {
    log.error("외부 호출 실패: " + e.getMessage());
}

// 개선: 예외 객체를 넘겨 스택을 남긴다
catch (ExternalException e) {
    log.error("외부 호출 실패 requestId={}", request.getId(), e);
}
```

운영 장애에서 가장 곤란한 상황은 무엇이 잘못됐는지 로그조차 없는 경우다.
시스템 차원의 분석성은 [qa-observability-rationale.md](./qa-observability-rationale.md)에서 이어서 다룬다.

## 5. 컨벤션은 사람이 아니라 도구가 본다

점검 항목
* `[인프라]` `MNT-5-01` 포맷터와 정적 분석이 빌드에 연결되어 있는가
* `[인프라]` `MNT-5-02` 규칙 위반이 경고가 아니라 실패로 처리되는가
* `[프로세스]` `MNT-5-03` 규칙 변경 시 기존 코드 일괄 적용 방침이 있는가

스타일 일관성은 중요하지만, 사람이 공백과 줄바꿈을 지적하는 것은 비용이 크고 감정 소모도 크다.
포맷터와 정적 분석 도구가 기계적으로 처리하면 사람은 도구가 못 잡는 설계와 로직에 집중할 수 있다.

```groovy
// 개선: 검사를 빌드에 묶어 위반 시 실패시킨다
plugins {
    id 'checkstyle'
    id 'com.github.spotbugs'
    id 'jacoco'
}

checkstyle {
    toolVersion = '10.17.0'
    maxWarnings = 0        // 경고를 남겨 두면 계속 쌓인다
}

spotbugs {
    effort = 'max'
    reportLevel = 'medium'
}

test {
    finalizedBy jacocoTestReport
}
```

경고를 허용하면 경고 수가 늘기만 하고 줄지 않는다.
0으로 두고 예외가 필요하면 명시적으로 억제하되 사유를 남긴다.

## 6. 측정 지표

| 지표 | 의미 | 기준 (예시값) |
|------|------|---------------|
| 순환 복잡도 | 분기 수 기반 복잡도 | 메서드당 10 이하 |
| 중복 코드 비율 | 복사된 로직의 양 | 5% 이하 |
| 도메인 간 순환 참조 | 구조 건전성 | 0건 |
| 변경 리드타임 | 커밋부터 배포까지 시간 | 1일 미만 (등급 B) |
| 변경 실패율 | 배포 중 장애를 유발한 비율 | 약 5% (등급 B) |
| 테스트 커버리지 | 실행된 코드 비율 | 목표로 삼지 않는다 |

커버리지는 코드가 실행됐는지만 알려 줄 뿐 제대로 검증됐는지는 말해 주지 않는다.
검증 없이 호출만 하는 테스트도 커버리지는 올린다.

커버리지를 쓰려면 숫자 자체가 아니라 **변경분 기준**으로 본다.
전체 70%를 목표로 삼는 것보다, 이번 변경분에 테스트가 없는 부분을 드러내는 편이 실효가 있다.

### 변경 리드타임과 변경 실패율의 근거

두 지표의 목표값은 DORA의 2024 Accelerate State of DevOps Report에서 관측된 최상위(elite) 집단의 수치다 (등급 B).

| 지표 | elite 집단 관측값 |
|------|-------------------|
| 배포 빈도 | 온디맨드(하루 여러 번) |
| 변경 리드타임 | 1일 미만 |
| 변경 실패율 | 약 5% |
| 장애 복구 시간 | 1시간 미만 |

주의할 점이 두 가지 있다.
첫째, 이 수치는 권장 목표가 아니라 상위 약 19% 집단의 관측 분포다. 곧바로 목표로 삼으면 대부분의 팀에게 비현실적이다.
둘째, DORA 자신이 변경 실패율은 다른 세 지표와 다르게 움직이는 이상치였다고 보고했다. 2024년에는 중간 집단이 상위 집단보다 변경 실패율이 낮게 나오는 역전이 관측되었다.
따라서 이 값은 절대 기준이 아니라 현재 위치를 가늠하는 참고선으로 쓴다.

## 7. 관련 문서

* 시스템 차원의 분석성: [qa-observability-rationale.md](./qa-observability-rationale.md)
* 변경 가능성과 교체 가능성: [qa-flexibility-rationale.md](./qa-flexibility-rationale.md)
* 추상화와 단순성의 충돌: [qa-tradeoffs-rationale.md](./qa-tradeoffs-rationale.md)

## 8. 참고 문헌

| 항목 | 링크 |
|------|------|
| DORA, Accelerate State of DevOps Report | https://dora.dev/research/ |
| ArchUnit (구조 규칙 테스트) | https://www.archunit.org/ |
