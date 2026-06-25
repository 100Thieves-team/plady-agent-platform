# plady-agent-platform

`plady-agent-platform` is the platform foundation repo for Plady agent services. It currently wraps the upstream `llm-wiki` MCP server and Hugo wiki UI, and defines the contracts that future platform work will implement under `agent.plady.io`.

Upstream code mirrors:

- `llm-wiki/`: https://github.com/geronimo-iia/llm-wiki
- `llm-wiki-hugo-cms/`: https://github.com/geronimo-iia/llm-wiki-hugo-cms

## Platform contracts

PLA-246 establishes the initial platform contracts in `docs/`:

- [`docs/platform-contract.md`](docs/platform-contract.md): root `plady.io` vs delegated `agent.plady.io` ownership, public endpoint contracts, Route 53 access note, and SSM parameter name contracts.
- [`docs/pla-244-handoff.md`](docs/pla-244-handoff.md): handoff contract for PLA-244 Slack ↔ Hermes integration work.

Current endpoint summary (the SSOT is [`docs/platform-contract.md`](docs/platform-contract.md)):

| Endpoint | Purpose |
| --- | --- |
| `https://wiki.agent.plady.io` | public wiki UI |
| `https://mcp.agent.plady.io/mcp` | bearer-token-protected llm-wiki MCP HTTP endpoint |
| `https://hermes.agent.plady.io` | Hermes Gateway public origin |
| `https://hermes.agent.plady.io/v1` | OpenAI-compatible Hermes base URL |
| `https://n8n.agent.plady.io` | reserved for later n8n work |
| OTEL collector | internal-only; no public endpoint |

Secret values must never be committed or pasted into Linear/GitHub/docs. Only the parameter names documented in [`docs/platform-contract.md`](docs/platform-contract.md) are part of this repo contract.

## Agent skills

Approved agent skills live under `.agents/skills/<name>/` as the SSOT. Claude-compatible skill discovery uses relative symlinks under `.claude/skills/<name>`.

```text
.agents/skills/linear-issue-session/
.agents/skills/linear-parallel-planner/
.claude/skills/linear-issue-session -> ../../.agents/skills/linear-issue-session
.claude/skills/linear-parallel-planner -> ../../.agents/skills/linear-parallel-planner
```

Do not copy unapproved skill/plugin expansions from abandoned worktrees into this repo.

## Docker Compose local run

```bash
export MCP_BEARER_TOKEN="dev-only-change-me"
docker compose up -d --build
```

Services:

| Service | URL | Purpose |
| --- | --- | --- |
| `mcp-proxy` | `http://localhost:18765/mcp` | local bearer-token-protected llm-wiki MCP HTTP endpoint |
| `wiki-ui` | `http://localhost:1313` | local Hugo wiki UI |

On first run, the `llm-wiki` container initializes a `100thieves` wiki space in local `./wiki-workspace`, and `wiki-ui` renders the same wiki content with curated pages (`/people`, `/topics`, `/sources`) plus raw source archive (`/raw`). `./wiki-workspace` is a separate git repo initialized by llm-wiki and is ignored by this wrapper repo.

MCP requests must include the `Authorization: Bearer $MCP_BEARER_TOKEN` header to pass through `mcp-proxy`.

Stop services:

```bash
docker compose down
```

Reset Compose volumes:

```bash
docker compose down -v
```

To delete local wiki data too, stop containers and remove `wiki-workspace/`.

## Wiki data repository

MCP ingest output (meeting notes, ADRs, mentoring notes, and other durable wiki knowledge) is stored in [`100Thieves-team/team-wiki-v2`](https://github.com/100Thieves-team/team-wiki-v2), not in this wrapper repo. See [`docs/wiki-data-repo.md`](docs/wiki-data-repo.md).

## Deployment status

The legacy EC2/Caddy deployment docs remain for historical wiki deployment context, but they are **not** the new `agent.plady.io` platform contract. New DNS/ACM/ALB/Terraform implementation belongs to PLA-247 and must follow [`docs/platform-contract.md`](docs/platform-contract.md).

Legacy references:

- [`docs/ec2-deployment-setup.md`](docs/ec2-deployment-setup.md)
- [`infra/terraform/ec2/README.md`](infra/terraform/ec2/README.md)

## Agent ingest workflow

`wiki_ingest` is the validation/index/git-commit step, not the AI compilation step itself. The MCP client agent is responsible for transforming raw documents into durable wiki knowledge. See [`docs/agent-ingest-workflow.md`](docs/agent-ingest-workflow.md).
