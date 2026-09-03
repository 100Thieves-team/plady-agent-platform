# 내부 OTEL Collector 런타임 (PLA-251)

이 문서는 `plady-agent-platform`의 **internal-only OpenTelemetry Collector**를 어떻게 띄우고 운영하는지에 대한 SSOT runbook입니다. endpoint/secret **이름 계약**은 [`platform-contract.md`](platform-contract.md)가 SSOT입니다.

## 무엇을 띄우는가

- 런타임: [`otel/opentelemetry-collector-contrib`](https://github.com/open-telemetry/opentelemetry-collector-contrib) 공개 이미지 (compose 기본 핀 `0.154.0`, `OTEL_IMAGE`로 override). **contrib** 배포판이어야 합니다 — `redaction` processor와 `file` exporter는 core 이미지에 없습니다.
- compose 서비스: `otel-collector` (profile `otel`). 기본 `docker compose up`에서는 뜨지 않습니다.
- config: 레포의 [`otel/collector-config.yaml`](../otel/collector-config.yaml)를 컨테이너 `/etc/otelcol-contrib/config.yaml`에 read-only mount.
- 영속화: 파일 export 산출물은 named volume `otel-data` → 컨테이너 `/var/lib/otel`.

### 네트워크/포트 (internal-only)

| 항목 | 값 |
| --- | --- |
| OTLP gRPC | `otel-collector:4317` (compose 네트워크 내부) |
| OTLP HTTP | `otel-collector:4318` (compose 네트워크 내부) |
| health | `otel-collector:13133` (내부) |
| host publish | **없음**. `ports:` 매핑을 두지 않고 `expose:`만 사용 |
| public endpoint | **없음**. `otel.agent.plady.io` 같은 public hostname을 만들지 않음. Caddy/ALB 라우팅 대상 아님 |

> OTEL은 계약상 internal-only입니다. local·EC2 모두 host publish 없이 compose 네트워크에만 노출합니다. 컨테이너 안에서 `0.0.0.0` 바인드는 **host publish가 없다는 전제** 하에 안전합니다. instrumentation을 보내는 쪽은 같은 compose 네트워크에서 `otel-collector:4317`(gRPC) 또는 `http://otel-collector:4318`(HTTP)로 보냅니다.

### 환경 변수

| 변수 | 용도 |
| --- | --- |
| `OTEL_IMAGE` | 이미지 override (기본 `otel/opentelemetry-collector-contrib:0.154.0`). contrib 배포판 유지 필수. |

이 서비스는 secret이 필요 없습니다(외부 백엔드로 보내지 않음). SSM/secret 참조 없음.

## Exporter 계약 — file/local-first

- 텔레메트리는 **파일로 로컬 우선** export 됩니다: `file` exporter → `/var/lib/otel/otel-data.json` (named volume `otel-data`), rotation `max_megabytes: 50` / `max_days: 7` / `max_backups: 3`.
- `debug` exporter는 `verbosity: basic`(건수만, 내용 미출력)으로 liveness 용도입니다.
- **외부/네트워크 백엔드로 보내는 exporter는 의도적으로 없습니다.** 팀 개발자 텔레메트리가 EC2 박스 밖으로 나가지 않습니다. 나중에 백엔드를 붙이려면 별도 이슈로 exporter를 추가하고 privacy 영향을 재검토하세요.

## Privacy / Sanitization 정책 (필수, 약화 금지)

실제 100 Thieves 팀 개발자 데이터가 이 collector로 흐르고 EC2에서 처리됩니다. config의 processor 파이프라인이 다음을 **강제**합니다:

- **raw prompt 저장 금지 / raw completion 저장 금지** — `attributes/scrub`가 record-level attribute의 prompt·completion·message·content 계열 key를 **삭제**하고, `transform/scrub`가 **span event attribute**(이벤트형 GenAI 계측이 prompt/completion을 담는 곳)의 같은 key를 삭제합니다.
- **secret/token 저장 금지** — `api_key`·`secret`·`token`·`authorization`·`password`·`credential`·`cookie`·`*_key` 계열 key 삭제(record + resource + span event) + `redaction/privacy`가 attribute 값의 Bearer·`sk-...`·AWS key·JWT를 **마스킹** + `transform/scrub`가 **log body** 안의 같은 값을 마스킹합니다.
- **PII 저장 금지** — `email`·`phone`·`ssn`·`credit_card` 계열 key 삭제 + email 등 값 마스킹(attribute 값 + log body).
- **processor별 적용 범위(중요)**: `attributes`/`redaction` processor는 **record-level attribute map만** 봅니다(span event·log body·resource/scope attribute·span name은 못 봅니다). 그래서 `transform/scrub`(OTTL)를 추가해 **resource attribute 키 삭제(전 시그널)** + **span event attribute 키 삭제** + **log body 값 마스킹**을 커버합니다.
- 파이프라인 순서(모든 시그널 traces/metrics/logs 공통): `memory_limiter → attributes/scrub → transform/scrub → redaction/privacy → batch → [file, debug]`.
- 과삭제(over-deletion)가 안전한 방향이므로 의도적으로 넓게 잡았습니다(예: `*token*` 키는 token-count usage 메트릭까지 삭제될 수 있음 — usage가 필요하면 해당 instrumentation에 맞춰 패턴을 정교화). 새 instrumentation이 위 패턴 밖의 민감 필드를 만들면 `otel/collector-config.yaml`의 패턴/키를 먼저 갱신하세요.
- **알려진 잔여 한계**(현재 sender가 없어 실측 불가): ① **span name**에 직접 박힌 PII/secret(예: SQL/URL을 span name으로 쓰는 계측)은 삭제하지 않습니다(이름 변경은 trace grouping을 깸). ② 비문자열(int/bytes) 값에 담긴 민감 데이터는 값 마스킹 대상이 아닙니다(키가 패턴에 걸리면 삭제됨). 실제 sender 연결 시 이 두 경우를 재점검하세요.

## Runbook (start / stop / validate)

```bash
# config 유효성 검증 (기동 없이)
docker run --rm -v "$PWD/otel/collector-config.yaml":/etc/otelcol-contrib/config.yaml:ro \
  otel/opentelemetry-collector-contrib:0.154.0 validate --config /etc/otelcol-contrib/config.yaml

# start (profile otel)
docker compose --profile otel up -d otel-collector

# logs (basic verbosity — 텔레메트리 내용 미포함)
docker compose logs -f otel-collector
```

> ⚠️ contrib 이미지는 **distroless**라 셸/`wget`/`ls`가 없습니다. `docker compose exec otel-collector sh/ls/wget ...`는 "executable file not found"로 실패합니다. health 확인과 파일 산출물 확인은 아래처럼 **사이드카/볼륨**으로 합니다.

```bash
# health: collector의 네트워크 네임스페이스에 일회용 curl 컨테이너를 붙여 확인
docker run --rm --network "container:$(docker compose ps -q otel-collector)" \
  curlimages/curl -fsS localhost:13133/ && echo

# 파일 산출물 확인: named volume을 busybox 사이드카로 마운트
#   <project>_otel-data 실제 볼륨명은 `docker volume ls`로 확인 (compose 프로젝트명 = 디렉터리명 소문자).
docker run --rm -v <project>_otel-data:/data busybox ls -la /data

# stop
docker compose --profile otel stop otel-collector
```

운영(EC2)도 동일하게 internal-only로 띄웁니다(여기서도 distroless라 사이드카로 확인):

```bash
docker compose --env-file .env.ec2 -f compose.ec2.yaml --profile otel up -d otel-collector
docker run --rm -v <project>_otel-data:/data busybox ls -la /data
```

### Sanitization 스모크(권장)

OTLP HTTP로 prompt/secret/email을 일부러 담은 샘플 trace를 `http://otel-collector:4318/v1/traces`로 보낸 뒤 `/var/lib/otel/otel-data.json`에 해당 값이 **남지 않는지** 육안 확인합니다(같은 compose 네트워크의 컨테이너에서 `curl` 사용).

## 개인 로컬 collector 예외 (2026-09-03 계약 개정)

위 privacy 정책은 **팀 텔레메트리가 공유 EC2로 흐르는** 플랫폼 collector에 대한 것이다. 개발자가 **자기 노트북에서 자기 텔레메트리만** 받아 프롬프트 습관·워크플로를 분석하는 용도는 별개의 인스턴스로 허용한다. 경계는 다음과 같다.

| 항목 | 플랫폼 collector (계약) | 개인 로컬 collector (예외) |
| --- | --- | --- |
| config | `otel/collector-config.yaml` | `otel/collector-config.local.yaml` |
| 기동 | `--profile otel` | `docker compose -f compose.otel-local.yaml up -d` (독립 compose, 서비스 `otel-collector-local`) |
| 수신 | compose 네트워크만, host publish 없음 | **`127.0.0.1:4317/4318` 만** publish (LAN/EC2 노출 없음) |
| 데이터 주체 | 팀 전원 | 그 노트북 사용자 본인 |
| 프롬프트·툴 상세 | **삭제** | **보존** (분석 목적) |
| 자격증명 키 / secret·PII 값 | 삭제 + 마스킹 | 삭제 + 마스킹 (동일 패턴, `token` 키는 usage 지표 보존 위해 제외) |
| 산출물 | `otel-data.json` | `otel-local.json` (같은 볼륨, 다른 파일) |

- 이 예외 config 를 EC2 에 올리거나, 다른 팀원의 CLI 를 내 collector 로 향하게 하는 것은 계약 위반이다.
- 보내는 쪽 설정: Claude Code 는 `~/.claude/settings.json` 의 `env` 에 `CLAUDE_CODE_ENABLE_TELEMETRY=1`, `OTEL_*_EXPORTER=otlp`, `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318`, `OTEL_LOG_USER_PROMPTS=1`, `OTEL_LOG_TOOL_DETAILS=1`. Codex 는 `~/.codex/config.toml` `[otel]` 에 `log_user_prompt = true` + `exporter`/`trace_exporter`/`metrics_exporter` 를 `http://localhost:4318/v1/{logs,traces,metrics}` 로. collector 가 꺼져 있으면 CLI 는 export 를 조용히 버린다 — 동작에는 영향 없다.
- 분석: `scripts/otel-report.py` (파일 export 를 읽어 자주 쓰는 프롬프트, 시간대별 활동, 툴 사용, 토큰/비용을 낸다).
- `otel-local.json` 은 내 프롬프트 원문이 들어 있는 파일이다. 노트북 밖으로 옮기지 않는다.

## 보안 주의사항

- host publish(`ports`) 금지 — local·EC2 모두. 공개 노출/TLS 종단은 PLA-247 ingress 뒤에서만 하며, **OTEL은 ingress 대상이 아닙니다.**
- 새 exporter로 외부 백엔드를 붙이면 데이터가 박스를 떠납니다. privacy 정책을 재검토하고 별도 이슈로 처리하세요.
- `otel-data` 볼륨은 sanitized 텔레메트리를 보관하지만, 검증 전이라면 민감 데이터로 취급하세요.

## PLA 핸드오프

- 내부 OTLP 타깃: `otel-collector:4317`(gRPC) / `otel-collector:4318`(HTTP). instrumentation을 추가하는 후속 작업이 이 타깃을 소비합니다.
- 이 이슈(PLA-251)는 **수신 자리와 sanitization/export 계약**만 제공합니다. 실제 sender(Hermes/MCP 등 instrumentation), 외부 백엔드, dashboard는 범위 밖입니다.
