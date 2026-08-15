# 보안 점검 항목의 근거

판정용 항목 목록은 [qa-security-guideline.md](./qa-security-guideline.md) 에 있다.
이 문서는 왜 그 기준인지와 예시를 담는다.

권한 수준에 맞게만 정보와 기능에 접근하도록 보호하는 정도를 뜻한다.

하위 특성
* **기밀성(confidentiality)**: 인가된 대상만 접근
* **무결성(integrity)**: 허가되지 않은 변경 방지
* **부인 방지(non-repudiation)**: 행위를 부인할 수 없게 증거 보존
* **책임 추적성(accountability)**: 행위를 주체까지 추적
* **진정성(authenticity)**: 주체가 주장하는 대상임을 증명
* **저항성(resistance)**: 공격 시도 중에도 기능 유지 (2023년판 추가)

> **수치에는 근거 등급이 표시되어 있다.**
> A는 산술로 도출된 값, B는 출처가 있는 값(링크 표기), C는 근거 없이 정한 예시값이다.
> C로 표시된 값은 그대로 채택하지 말고 측정 후 팀이 확정한다.
> 등급 정의는 quality-attributes.md의 "판정 기준 수치의 성격"을 참고한다.

## 1. 인가가 인증보다 자주 뚫린다

로그인 여부만 확인하고 리소스 소유권을 확인하지 않는 IDOR(insecure direct object reference)이 실무에서 가장 흔한 취약점이다.

점검 항목
* `[코드]` `SEC-1-01` 리소스 접근 시 소유권 또는 권한을 검증하는가
* `[코드]` `SEC-1-02` 검증을 클라이언트가 보낸 식별자가 아니라 인증 주체 기준으로 하는가
* `[코드]` `SEC-1-03` 목록 조회에서도 소유자 조건이 쿼리에 포함되는가
* `[설계]` `SEC-1-04` 권한 모델이 문서화되어 있고 기본값이 거부인가

```java
// 점검 대상: 인증만 확인. 남의 리소스도 조회된다
@GetMapping("/v1/records/{recordId}")
public RecordResponse get(@PathVariable Long recordId) {
    return recordService.get(recordId);
}

// 개선: 인증 주체 기준으로 소유권을 검증
@GetMapping("/v1/records/{recordId}")
public RecordResponse get(@PathVariable Long recordId,
                          @AuthenticationPrincipal UserPrincipal principal) {
    return recordService.getOwned(recordId, principal.getId());
}
```

```java
// 점검 대상: 요청 본문의 userId를 그대로 신뢰
public void updateProfile(ProfileRequest req) {
    userRepository.findById(req.getUserId());   // 남의 id를 넣으면 남의 정보 수정
}
```

기본값은 거부여야 한다. 새 엔드포인트를 추가할 때 인가 설정을 잊으면 공개되는 구조는 위험하다.

```java
// 개선: 명시적으로 허용한 경로 외에는 전부 인증을 요구한다
@Bean
public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
    return http
        .authorizeHttpRequests(auth -> auth
            .requestMatchers("/health/**", "/v1/public/**").permitAll()
            .requestMatchers("/v1/admin/**").hasRole("ADMIN")
            .anyRequest().authenticated())     // 누락된 경로는 자동으로 보호된다
        .build();
}
```

권한 없는 접근에는 존재 여부까지 노출하지 않는다.

| 상황 | 응답 |
|------|------|
| 권한 없음 | 403. 리소스 존재 여부와 무관 |
| 권한 있으나 리소스 없음 | 404 |
| 인증 없음 | 401 |

## 2. 인젝션

점검 항목
* `[코드]` `SEC-2-01` 쿼리를 문자열 연결로 조립하지 않는가
* `[코드]` `SEC-2-02` 정렬 컬럼, 테이블명 등 바인딩 불가 요소를 화이트리스트로 검증하는가
* `[코드]` `SEC-2-03` 외부 명령 실행에 사용자 입력을 직접 넣지 않는가

```java
// 점검 대상: SQL 인젝션
String sql = "SELECT * FROM app_user WHERE email = '" + email + "'";

// 개선: 바인딩 파라미터
jdbcTemplate.query("SELECT * FROM app_user WHERE email = ?", rowMapper, email);
```

정렬 컬럼처럼 바인딩할 수 없는 자리는 화이트리스트로 막는다.

```java
// 점검 대상: 정렬 컬럼을 그대로 연결 -> ORDER BY 인젝션
String sql = "SELECT * FROM record ORDER BY " + sortColumn;

// 개선: 허용 목록으로 제한
private static final Set<String> SORTABLE =
    Set.of("created_at", "updated_at", "status");

if (!SORTABLE.contains(sortColumn)) {
    throw new IllegalArgumentException("정렬할 수 없는 컬럼입니다");
}
```

JPA에서도 네이티브 쿼리에 문자열을 붙이면 동일하게 뚫린다.

DB 계정 권한으로도 피해 범위를 줄인다.

```sql
-- 개선: 애플리케이션 계정에서 스키마 변경과 대량 삭제 권한을 뺀다
CREATE USER 'app_user'@'%' IDENTIFIED BY '...';
GRANT SELECT, INSERT, UPDATE, DELETE ON app_db.* TO 'app_user'@'%';
-- DROP, ALTER, CREATE, FILE 권한은 부여하지 않는다
```

| 항목 | 기준 |
|------|------|
| 애플리케이션 DB 계정 | DML만. DDL 권한 없음 |
| 마이그레이션 계정 | 배포 시에만 사용. 별도 계정 |
| 읽기 전용 기능 | SELECT 전용 계정 사용 |

## 3. 입력 검증은 서버가 한다

클라이언트 검증은 UX용이고 신뢰 경계는 서버다.

점검 항목
* `[코드]` `SEC-3-01` 모든 외부 입력을 서버에서 검증하는가
* `[코드]` `SEC-3-02` 블랙리스트가 아니라 화이트리스트 방식인가
* `[코드]` `SEC-3-03` 길이와 범위 상한이 있는가
* `[코드]` `SEC-3-04` 파일 업로드에서 확장자, MIME 타입, 크기, 저장 경로를 검증하는가
* `[인프라]` `SEC-3-05` 요청 본문 크기 상한이 설정되어 있는가

```java
// 개선: Bean Validation으로 형식과 범위를 선언적으로 강제
public record CreateRequest(
    @NotNull Long resourceId,
    @Min(1) @Max(999) int quantity,
    @Size(max = 200) String memo
) {}
```

```java
// 점검 대상: 파일명을 그대로 경로에 사용 -> 경로 순회 공격 가능
Path target = uploadDir.resolve(file.getOriginalFilename());

// 개선: 이름을 서버가 생성하고 경로를 정규화해 검증
String stored = UUID.randomUUID() + extensionOf(file);
Path target = uploadDir.resolve(stored).normalize();
if (!target.startsWith(uploadDir)) {
    throw new IllegalArgumentException("잘못된 경로입니다");
}
```

판정 기준 (등급 C. 근거 없음)

| 항목 | 상한 |
|------|------|
| 요청 본문 | 1MB (파일 업로드 제외) |
| 업로드 파일 | 10MB |
| 문자열 필드 | 용도별 명시. 무제한 금지 |
| 페이지 크기 | 100 |
| 배열 파라미터 길이 | 100 |

```yaml
# 개선: 애플리케이션 진입 지점에서 크기 상한을 건다
spring:
  servlet:
    multipart:
      max-file-size: 10MB
      max-request-size: 20MB
server:
  max-http-request-header-size: 16KB
```

## 4. 민감 정보 보호

점검 항목
* `[코드]` `SEC-4-01` 비밀번호를 단방향 해시로 저장하는가 (BCrypt, Argon2 등)
* `[코드]` `SEC-4-02` 로그와 예외 메시지에 개인정보, 인증 토큰, 쿼리 원문이 남지 않는가
* `[코드]` `SEC-4-03` 응답 DTO가 엔티티를 그대로 노출하지 않는가
* `[설계]` `SEC-4-04` 저장 시 암호화가 필요한 항목을 등급으로 구분했는가

```java
// 점검 대상: 예외 메시지에 민감 정보와 내부 구조 노출
throw new RuntimeException("SELECT ... FROM app_user WHERE national_id=" + nationalId);

// 개선: 외부에는 일반화된 메시지, 내부 추적은 식별자로
log.warn("사용자 조회 실패 userId={}", userId);
throw new UserNotFoundException(userId);
```

```java
// 점검 대상: 엔티티를 그대로 응답 -> password, 내부 플래그까지 직렬화됨
return userRepository.findById(id).orElseThrow();

// 개선: 필요한 필드만 담은 응답 DTO
return UserResponse.from(user);
```

데이터 등급별 처리 기준 (예시값)

| 등급 | 예시 | 저장 | 로그 | 보존 |
|------|------|------|------|------|
| 1급 | 고유 식별번호, 금융 계좌, 인증 자격증명 | 암호화 필수 | 전면 금지 | 법정 기간 후 파기 |
| 2급 | 이름, 연락처, 주소, 이메일 | 평문 허용, 접근 통제 | 마스킹 후 기록 | 탈퇴 후 파기 |
| 3급 | 사용자 활동 기록, 거래 내역 | 평문 | 식별자만 기록 | 정책에 따름 |
| 4급 | 공개 콘텐츠, 기준 정보 | 평문 | 제한 없음 | 제한 없음 |

비밀번호 해시 기준 (등급 B. OWASP Password Storage Cheat Sheet)

출처: https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html

| 알고리즘 | OWASP 최소 권장 |
|----------|-----------------|
| Argon2id (1순위) | 메모리 19MiB, 반복 2회, 병렬성 1. 또는 메모리 46MiB, 반복 1회, 병렬성 1 |
| scrypt (Argon2id 불가 시) | CPU/메모리 비용 2^17, 블록 크기 8, 병렬성 1 |
| bcrypt (레거시) | 작업 인자 10 이상, 입력 72바이트 제한 |
| PBKDF2 (FIPS-140 필요 시) | 반복 600,000 이상, HMAC-SHA-256 |

OWASP는 Argon2id를 1순위로 두고, bcrypt는 Argon2와 scrypt를 쓸 수 없는 레거시 환경용으로 분류한다.
bcrypt 작업 인자는 검증 서버 성능이 허용하는 한 크게 잡되 최소 10 이상이며, 대부분의 구현이 72바이트를 넘는 입력을 잘라내므로 길이 제한을 함께 걸어야 한다.

파라미터는 하드웨어 성능 향상에 따라 주기적으로 상향해야 한다. 재검토 주기 자체는 등급 C이며 팀에서 정한다.

## 5. 책임 추적성과 부인 방지

누가 언제 무엇을 바꿨는지 남지 않으면 사고 후 복기가 불가능하다.

점검 항목
* `[코드]` `SEC-5-01` 상태 변경 이력에 변경 주체가 기록되는가
* `[코드]` `SEC-5-02` 관리자 행위에 감사 로그가 남는가
* `[인프라]` `SEC-5-03` 이력이 애플리케이션에서 삭제되지 않도록 보호되는가
* `[프로세스]` `SEC-5-04` 감사 로그를 정기적으로 검토하는가

```java
// 개선: 변경 주체를 상태 이력에 함께 남긴다
record.changeStatus(Status.CANCELED, ChangedBy.ADMIN, adminId);
```

시스템 자동 처리와 사람의 처리를 구분할 수 있어야 한다.

```sql
-- 개선: 감사 로그는 애플리케이션 계정이 지울 수 없게 한다
CREATE TABLE audit_log (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    actor_id    BIGINT       NOT NULL,
    actor_type  VARCHAR(20)  NOT NULL,   -- USER, ADMIN, SYSTEM
    action      VARCHAR(50)  NOT NULL,
    target_type VARCHAR(50)  NOT NULL,
    target_id   VARCHAR(64)  NOT NULL,
    detail      JSON         NULL,
    created_at  DATETIME(3)  NOT NULL,
    KEY idx_audit_target (target_type, target_id, created_at),
    KEY idx_audit_actor (actor_id, created_at)
);

-- 애플리케이션 계정에는 INSERT와 SELECT만 부여한다
GRANT SELECT, INSERT ON app_db.audit_log TO 'app_user'@'%';
```

| 감사 대상 | 기록 항목 | 보존 |
|-----------|-----------|------|
| 관리자 로그인 | 시각, IP, 성공 여부 | 1년 |
| 개인정보 조회 | 조회자, 대상, 시각, 사유 | 3년 |
| 상태 강제 변경 | 변경자, 이전값, 이후값 | 3년 |
| 금전 처리 실행 | 실행자, 금액, 승인자 | 5년 |
| 권한 부여와 회수 | 실행자, 대상, 권한 | 5년 |

### 감사 로그 검토 절차

```
월 1회 수행

1. 개인정보 조회 이력 중 사유가 비어 있거나 형식적인 건 추출
2. 업무 시간 외 관리자 접근 건 추출
3. 동일 관리자의 대량 조회(일 100건 초과) 추출
4. 각 건에 대해 담당자 확인. 설명되지 않는 건은 별도 조사
5. 검토 수행 사실과 결과를 기록
```

감사 로그는 쌓기만 하고 보지 않으면 저장 비용만 발생한다.
보는 절차가 있어야 억지력이 생긴다.

## 6. 저항성

공격이나 이상 트래픽 중에도 기능을 유지하는 능력이다.

점검 항목
* `[인프라]` `SEC-6-01` 로그인, 인증번호 발송 등에 시도 횟수 제한이 있는가
* `[인프라]` `SEC-6-02` IP 또는 계정 단위 레이트 리밋이 있는가
* `[코드]` `SEC-6-03` 대량 조회 API에 상한과 인증이 걸려 있는가
* `[코드]` `SEC-6-04` 인증 실패 응답이 계정 존재 여부를 구분해서 알려 주지 않는가

```java
// 점검 대상: 존재하는 계정과 없는 계정을 다른 메시지로 알려 줌 -> 계정 열거 가능
if (member == null) throw new BadCredentialsException("존재하지 않는 이메일입니다");
if (!matches(password)) throw new BadCredentialsException("비밀번호가 틀립니다");

// 개선: 동일한 메시지
throw new BadCredentialsException("이메일 또는 비밀번호가 올바르지 않습니다");
```

응답 시간 차이로도 계정 존재 여부가 드러난다.
계정이 없을 때도 해시 검증에 준하는 시간을 소비하도록 맞춘다.

판정 기준 (등급 C. 근거 없음. 실제 사용 패턴을 관측한 뒤 확정한다)

| 대상 | 제한 | 초과 시 |
|------|------|---------|
| 로그인 시도 | 계정당 5회 / 15분 | 15분 잠금 |
| 로그인 시도 | IP당 30회 / 15분 | 차단 |
| 인증번호 발송 | 번호당 5회 / 시간 | 거절 |
| 비밀번호 재설정 | 계정당 3회 / 시간 | 거절 |
| 일반 API | 계정당 100회 / 분 | 429 응답 |
| 목록 조회 API | 계정당 20회 / 분 | 429 응답 |

`429` 응답에는 `Retry-After` 헤더를 함께 내려 클라이언트가 재시도 시점을 알 수 있게 한다.

## 7. 측정 지표

| 지표 | 수집 방법 | 기준 (예시값) |
|------|-----------|---------------|
| 알려진 취약점 있는 의존성 수 | 의존성 스캐너 | 심각도 High 이상 0건 |
| 정적 분석 보안 경고 수 | SAST 도구 | 신규 0건 |
| 취약점 발견부터 패치까지 | 이슈 트래커 | Critical 7일, High 30일 |
| 인증 실패율 | 로그인 실패 메트릭 | 평시 대비 3배 급증 시 경보 |
| 감사 로그 검토 수행률 | 검토 기록 | 월 1회 100% |
| 권한 검증 누락 엔드포인트 | 자동 점검 테스트 | 0건 |

권한 누락은 테스트로 강제할 수 있다.

```java
// 개선: 인증 없이 접근 가능한 엔드포인트를 명시적 목록과 대조한다
@Test
void 공개_엔드포인트_외에는_인증을_요구한다() {
    Set<String> allowedPublic = Set.of("/health", "/v1/public");

    for (String path : allEndpoints()) {
        if (allowedPublic.stream().noneMatch(path::startsWith)) {
            mockMvc.perform(get(path)).andExpect(status().isUnauthorized());
        }
    }
}
```

## 8. 관련 문서

* 감사 로그와 추적: [qa-observability-rationale.md](./qa-observability-rationale.md)
* 무결성과 동시 수정: [qa-data-integrity-rationale.md](./qa-data-integrity-rationale.md)
* 보안 비용과 성능의 충돌: [qa-tradeoffs-rationale.md](./qa-tradeoffs-rationale.md)

## 9. 참고 문헌

| 항목 | 링크 |
|------|------|
| OWASP Password Storage Cheat Sheet (해시 파라미터) | https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html |
| OWASP Top 10 | https://owasp.org/www-project-top-ten/ |
| OWASP Cheat Sheet Series | https://cheatsheetseries.owasp.org/ |
