# 100Thieves wiki MCP

기존 코드베이스를 비우고 upstream 코드를 그대로 받은 상태입니다.

- `llm-wiki/`: https://github.com/geronimo-iia/llm-wiki
- `llm-wiki-hugo-cms/`: https://github.com/geronimo-iia/llm-wiki-hugo-cms

## Docker Compose 실행

```bash
docker compose up -d --build
```

실행되는 서비스:

| Service | URL | 용도 |
| --- | --- | --- |
| `llm-wiki` | `http://localhost:18765/mcp` | llm-wiki MCP HTTP server |
| `wiki-ui` | `http://localhost:1313` | Hugo wiki UI |

처음 실행하면 `llm-wiki` 컨테이너가 로컬 `./wiki-workspace`에 `100thieves` wiki space를 만들고, `wiki-ui`가 같은 wiki content를 Hugo로 보여줍니다. `./wiki-workspace`는 llm-wiki가 init하는 별도 git repo라서 이 wrapper repo에서는 ignore합니다.

중지:

```bash
docker compose down
```

설정 볼륨까지 초기화하려면:

```bash
docker compose down -v
```

wiki 데이터까지 지우려면 컨테이너를 내린 뒤 로컬 `wiki-workspace/` 디렉터리를 삭제하세요.
