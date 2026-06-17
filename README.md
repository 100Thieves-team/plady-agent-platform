# 100Thieves wiki MCP

기존 코드베이스를 비우고 upstream 코드를 그대로 받은 상태입니다.

- `llm-wiki/`: https://github.com/geronimo-iia/llm-wiki
- `llm-wiki-hugo-cms/`: https://github.com/geronimo-iia/llm-wiki-hugo-cms

## Docker Compose 실행

```bash
export MCP_BEARER_TOKEN="dev-only-change-me"
docker compose up -d --build
```

실행되는 서비스:

| Service | URL | 용도 |
| --- | --- | --- |
| `mcp-proxy` | `http://localhost:18765/mcp` | Bearer token으로 보호되는 llm-wiki MCP HTTP endpoint |
| `wiki-ui` | `http://localhost:1313` | Hugo wiki UI |

처음 실행하면 `llm-wiki` 컨테이너가 로컬 `./wiki-workspace`에 `100thieves` wiki space를 만들고, `wiki-ui`가 같은 wiki content를 Hugo로 보여줍니다. UI는 curated page(`/people`, `/topics`, `/sources`)와 raw source archive(`/raw`)를 함께 노출합니다. `./wiki-workspace`는 llm-wiki가 init하는 별도 git repo라서 이 wrapper repo에서는 ignore합니다.

MCP 요청은 `Authorization: Bearer $MCP_BEARER_TOKEN` 헤더가 있어야 `mcp-proxy`를 통과합니다.

중지:

```bash
docker compose down
```

설정 볼륨까지 초기화하려면:

```bash
docker compose down -v
```

wiki 데이터까지 지우려면 컨테이너를 내린 뒤 로컬 `wiki-workspace/` 디렉터리를 삭제하세요.

## Wiki 데이터 저장소

MCP ingest로 쌓이는 실제 회의록/ADR/멘토링 데이터는 이 wrapper repo가 아니라 `wiki-workspace/`에 clone된 [`100Thieves-team/team-wiki-v2`](https://github.com/100Thieves-team/team-wiki-v2)에 저장됩니다. 자세한 내용은 [`docs/wiki-data-repo.md`](docs/wiki-data-repo.md)를 참고하세요.

## EC2 배포

EC2 한 대와 ECR repositories/GitHub Actions OIDC role을 만드는 Terraform 설정은 `infra/terraform/ec2/`에 있습니다.
저장소 clone은 PAT 대신 GitHub Deploy Key를 SSM Parameter Store SecureString에 저장해서 자동화하고, EC2는 GitHub Actions가 ECR에 올린 prebuilt image를 pull합니다. 운영 노출은 Caddy + ZeroSSL로 `https://wiki.plady.kro.kr`와 `https://wiki.plady.kro.kr/mcp`를 사용합니다.

```bash
cd infra/terraform/ec2
cp terraform.tfvars.example terraform.tfvars
terraform init
terraform plan
terraform apply
```

실제 배포자가 따라갈 단계별 절차는 [`docs/ec2-deployment-setup.md`](docs/ec2-deployment-setup.md)를 참고하세요. 자세한 Terraform 설정값과 주의사항은 [`infra/terraform/ec2/README.md`](infra/terraform/ec2/README.md)에 있습니다.
MCP Bearer token은 SSM SecureString `/100thieves/wiki/mcp-bearer-token`에 고정 저장되며, 서버 재시작만으로 바뀌지 않습니다. SSM 값을 EC2 런타임에 다시 반영해야 하면 `scripts/refresh-ec2-runtime-env.sh`를 사용하세요.
Codex client에는 `scripts/configure-codex-mcp.sh`로 MCP endpoint를 추가하고, token은 `LLM_WIKI_MCP_BEARER_TOKEN` 환경변수로 주입합니다. GUI Codex용 token 환경변수는 `scripts/set-codex-mcp-token-env.sh`로 macOS login session에 설정하세요.
