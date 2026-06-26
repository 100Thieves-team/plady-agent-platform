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

- **raw prompt 저장 금지 / raw completion 저장 금지** — `attributes/scrub`가 GenAI/LLM prompt·completion·message·content 계열 attribute key를 **삭제**(마스킹이 아니라 삭제)합니다.
- **secret/token 저장 금지** — `api_key`·`secret`·`token`·`authorization`·`password`·`credential`·`cookie`·`*_key` 계열 key 삭제 + `redaction/privacy`가 Bearer 토큰·`sk-...`·AWS access key·JWT 값을 **마스킹**합니다.
- **PII 저장 금지** — `email`·`phone`·`ssn`·`credit_card` 계열 key 삭제 + email 값 마스킹.
- 파이프라인 순서(모든 시그널 traces/metrics/logs 공통): `memory_limiter → attributes/scrub(키 삭제) → redaction/privacy(값 마스킹) → batch → [file, debug]`.
- 과삭제(over-deletion)가 안전한 방향이므로 의도적으로 넓게 잡았습니다. 새 instrumentation이 위 패턴 밖의 민감 필드를 만들면 `otel/collector-config.yaml`의 패턴/키를 먼저 갱신하세요.

## Runbook (start / stop / validate)

```bash
# config 유효성 검증 (기동 없이)
docker run --rm -v "$PWD/otel/collector-config.yaml":/etc/otelcol-contrib/config.yaml:ro \
  otel/opentelemetry-collector-contrib:0.154.0 validate --config /etc/otelcol-contrib/config.yaml

# start (profile otel)
docker compose --profile otel up -d otel-collector

# logs (basic verbosity — 텔레메트리 내용 미포함)
docker compose logs -f otel-collector

# health (컨테이너 내부에서; host publish 없음)
docker compose exec otel-collector wget -qO- localhost:13133/ || true

# 파일 산출물 확인
docker compose exec otel-collector ls -la /var/lib/otel/

# stop
docker compose --profile otel stop otel-collector
```

운영(EC2)도 동일하게 internal-only로 띄웁니다:

```bash
docker compose --env-file .env.ec2 -f compose.ec2.yaml --profile otel up -d otel-collector
docker compose --env-file .env.ec2 -f compose.ec2.yaml exec otel-collector ls -la /var/lib/otel/
```

### Sanitization 스모크(권장)

OTLP HTTP로 prompt/secret/email을 일부러 담은 샘플 trace를 `http://otel-collector:4318/v1/traces`로 보낸 뒤 `/var/lib/otel/otel-data.json`에 해당 값이 **남지 않는지** 육안 확인합니다(같은 compose 네트워크의 컨테이너에서 `curl` 사용).

## 보안 주의사항

- host publish(`ports`) 금지 — local·EC2 모두. 공개 노출/TLS 종단은 PLA-247 ingress 뒤에서만 하며, **OTEL은 ingress 대상이 아닙니다.**
- 새 exporter로 외부 백엔드를 붙이면 데이터가 박스를 떠납니다. privacy 정책을 재검토하고 별도 이슈로 처리하세요.
- `otel-data` 볼륨은 sanitized 텔레메트리를 보관하지만, 검증 전이라면 민감 데이터로 취급하세요.

## PLA 핸드오프

- 내부 OTLP 타깃: `otel-collector:4317`(gRPC) / `otel-collector:4318`(HTTP). instrumentation을 추가하는 후속 작업이 이 타깃을 소비합니다.
- 이 이슈(PLA-251)는 **수신 자리와 sanitization/export 계약**만 제공합니다. 실제 sender(Hermes/MCP 등 instrumentation), 외부 백엔드, dashboard는 범위 밖입니다.
