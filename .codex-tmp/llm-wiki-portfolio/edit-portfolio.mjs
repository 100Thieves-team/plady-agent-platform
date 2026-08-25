import fs from "node:fs/promises";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const buildDir = "/Users/luna/Desktop_nonsync/teams/100-thieves/100Thieves-wiki-mcp/.codex-tmp/llm-wiki-portfolio";
const starterPath = `${buildDir}/template-starter.pptx`;
const outputPath = "/Users/luna/Desktop_nonsync/teams/100-thieves/100Thieves-wiki-mcp/artifacts/Junseo_Bae_Portfolio_with_LLM_Wiki.pptx";
const previewDir = `${buildDir}/final-preview`;
const layoutDir = `${buildDir}/final-layout`;
let expectedById;
let runtimeBySlideAndText;

async function saveBlob(path, blob) {
  await fs.writeFile(path, new Uint8Array(await blob.arrayBuffer()));
}

function replaceText(presentation, anchor, oldText, newText) {
  const expected = expectedById.get(anchor);
  if (!expected) throw new Error(`Missing expected starter anchor: ${anchor}`);
  const key = `${expected.slide}\u0000${oldText}`;
  const candidates = runtimeBySlideAndText.get(key) ?? [];
  if (candidates.length !== 1) {
    throw new Error(`Expected one runtime match for slide ${expected.slide}: ${oldText}; found ${candidates.length}`);
  }
  const shape = presentation.resolve(candidates[0]);
  if (oldText.includes("\n")) {
    shape.text = newText;
  } else {
    shape.text.replace(oldText, newText);
  }
}

function setSources(slide, lines) {
  slide.speakerNotes.textFrame.setText([
    "[Sources]",
    ...lines.map((line) => `- ${line}`),
    "[/Sources]",
  ]);
  slide.speakerNotes.setVisible(true);
}

async function main() {
  await fs.mkdir(previewDir, { recursive: true });
  await fs.mkdir(layoutDir, { recursive: true });

  const presentation = await PresentationFile.importPptx(await FileBlob.load(starterPath));
  const expectedText = await fs.readFile(`${starterPath}.inspect.ndjson`, "utf8");
  const expectedRecords = expectedText.trim().split("\n").map((line) => JSON.parse(line));
  expectedById = new Map(expectedRecords.filter((record) => record.id).map((record) => [record.id, record]));
  const runtimeSnapshot = await presentation.inspect({ kind: "textbox", maxChars: 120000 });
  runtimeBySlideAndText = new Map();
  for (const line of runtimeSnapshot.ndjson.trim().split("\n")) {
    const record = JSON.parse(line);
    const key = `${record.slide}\u0000${record.text}`;
    const ids = runtimeBySlideAndText.get(key) ?? [];
    ids.push(record.id);
    runtimeBySlideAndText.set(key, ids);
  }

  // Slide 16 — LLM Wiki Platform cover.
  replaceText(presentation, "sh/lkz2dov6", "BACKEND ENGINEER PORTFOLIO", "BACKEND ENGINEER PORTFOLIO");
  replaceText(presentation, "sh/wje5wrq5", "Cluverse", "LLM Wiki");
  replaceText(presentation, "sh/hkn65w7q", "트래픽과 실패 경계를\n측정 가능한 구조로 바꿨다", "흩어진 팀 지식을\n운영 가능한 자산으로 바꿨다");
  replaceText(presentation, "sh/ilw7y18b", "배준서 · Junseo Bae\nJava / Spring / MySQL / Redis / AWS", "배준서 · Junseo Bae\nRust / MCP / Docker / Terraform / AWS");
  replaceText(presentation, "sh/jm5o76pg", "증상", "지식 수집");
  replaceText(presentation, "sh/4nyp0bq1", "원인", "권한 경계");
  replaceText(presentation, "sh/5o769w7m", "경계", "Git 내구성");
  replaceText(presentation, "sh/69g72187", "검증", "운영 자동화");
  replaceText(presentation, "sh/jixkbed0", "문제를 하나의 현상으로 보지 않는다", "엔진보다 운영 경계를 설계했다");
  replaceText(presentation, "sh/yho3itwf", "2026", "2026");
  setSources(presentation.slides.getItem(15), [
    "README.md — upstream llm-wiki를 감싼 plady-agent-platform의 범위와 서비스 구성",
    "llm-wiki/README.md — Git-backed Markdown wiki, MCP/ACP, 단일 Rust 바이너리",
    "git history — Junseo Bae의 2026-06~2026-08 플랫폼 통합 작업",
  ]);

  // Slide 17 — ingest-time knowledge accumulation.
  replaceText(presentation, "sh/8budczqh", "PROJECT · CLUVERSE", "PROJECT · LLM WIKI PLATFORM");
  replaceText(presentation, "sh/va9cr65c", "학교의 벽보다 관심사의 연결을 먼저 설계했다", "질의 때마다 답을 버리지 않고, ingest에서 지식을 누적했다");
  replaceText(presentation, "sh/5gbux0ne", "02", "17");
  replaceText(presentation, "sh/kf2dov6t", "전국 대학생이 학과·관심사로 모이고, 모집에서 실제 협업까지 이어지는 커뮤니티다.", "오픈소스 llm-wiki의 DKR 패턴을 팀 위키의 수집·검증·검색 흐름으로 연결했다.");
  replaceText(presentation, "sh/jetcvq5o", "관심사·학과\n보드", "원문 보존");
  replaceText(presentation, "sh/idkvmlo3", "모집·지원", "에이전트 합성");
  replaceText(presentation, "sh/lk7ulwna", "그룹 운영", "Schema 검증·색인");
  replaceText(presentation, "sh/0jytcr6p", "스파이크에서도\n읽기 흐름 보호", "Git 이력으로\n지식 축적");
  replaceText(presentation, "sh/l83eh47q", "기술 목표", "설계 목표");
  replaceText(presentation, "sh/m9cva98b", "사람이 몰려도 핵심 조회·쓰기의 성공률과 tail latency가 무너지지 않는 구조", "원문·정규화 지식·변경 이력을 분리하되 한 저장소 계약으로 연결");
  replaceText(presentation, "sh/nalwjepw", "개인 프로젝트 · 2026.01–2026.07", "팀 플랫폼 · 2026.06–2026.08");
  setSources(presentation.slides.getItem(16), [
    "llm-wiki/README.md — DKR, typed frontmatter, Tantivy index, Git history",
    "docs/agent-ingest-workflow.md — agent compile → direct write → wiki_ingest 책임 분리",
    "docs/wiki-data-repo.md — raw/wiki 데이터 계층과 team-wiki-v2 backing 계약",
  ]);

  // Slide 18 — platform architecture.
  replaceText(presentation, "sh/50rqtgni", "ARCHITECTURE · LOAD-TEST ENVIRONMENT", "ARCHITECTURE · AGENT KNOWLEDGE PLATFORM");
  replaceText(presentation, "sh/1gbalc7e", "비용을 고정해 구조 변경의 효과만 비교했다", "Rust 엔진과 운영 플랫폼의 책임을 분리했다");
  replaceText(presentation, "sh/rq9sfipc", "04", "18");
  replaceText(presentation, "sh/qp0b6dor", "Terraform base/test 스택을 분리해 같은 조건으로 생성·폐기하는 검증 인프라", "엔진은 지식 연산에 집중하고, 인증·라우팅·UI·동기화·관측은 플랫폼 경계로 분리했다.");
  replaceText(presentation, "sh/dcrahs72", "검증 인프라", "운영 인프라");
  replaceText(presentation, "sh/crit8n6x", "k6\nLoad Generator", "Agent / Slack");
  replaceText(presentation, "sh/bmtcrmpg", "AWS ALB\nHTTPS", "Caddy / ALB\nHTTPS");
  replaceText(presentation, "sh/alkbihov", "ECS on EC2\napp 1 · t3.small", "llm-wiki MCP\nRust engine");
  replaceText(presentation, "sh/ofa1cji5", "ECS on EC2\napp 2 · t3.small", "Hugo Wiki UI\nread model");
  replaceText(presentation, "sh/pgjilozq", "MySQL 8\nt3.small", "team-wiki-v2\nGit backing");
  replaceText(presentation, "sh/2tsja90f", "Redis\nt3.micro", "OTEL\nlocal-first");
  replaceText(presentation, "sh/3u10jeh0", "S3 + Lambda\nimage path", "SSM Deploy Key\nrepo-scoped");
  replaceText(presentation, "sh/grq18zi9", "Prometheus\n+ Grafana", "Hermes\nGateway");
  replaceText(presentation, "sh/z25ofmp8", "애플리케이션 2대 · DB 1대 · Redis 1대 · 측정 노드 분리", "단일 엔진 · 공유 wiki-data 볼륨 · 인증 프록시 · Git backing 분리");
  replaceText(presentation, "sh/y1w7mhon", "사양을 늘려 얻은 TPS와 구조 변경으로 얻은 TPS를 섞지 않았다.", "업스트림 엔진 교체와 플랫폼 운영을 독립적으로 변경할 수 있게 했다.");
  setSources(presentation.slides.getItem(17), [
    "README.md — 로컬/운영 서비스 구성과 공개 엔드포인트",
    "compose.ec2.yaml — caddy, mcp-proxy, llm-wiki, wiki-ui, wiki-data-sync, hermes-gateway",
    "docs/platform-contract.md — DNS/ACM/ALB/SSM 경계",
    "docs/otel-collector.md — 내부 전용 OTLP와 local-first export",
  ]);

  // Slide 19 — MCP tool authorization tiers.
  replaceText(presentation, "sh/2ps3ilo3", "METHOD · SLO", "CASE 01 · MCP TOOL BOUNDARY");
  replaceText(presentation, "sh/kze90vah", "최대 TPS보다 먼저 ‘통과 조건’을 고정했다", "도구는 연결보다 권한 경계가 먼저였다");
  replaceText(presentation, "sh/61gb2lsn", "03", "19");
  replaceText(presentation, "sh/72psvq9s", "숫자가 커져도 느리거나 실패하면 제공한 처리량이 아니다.", "실패 비용에 따라 자동 허용·사람 승인·기본 차단으로 계약했다.");
  replaceText(presentation, "sh/fqpsza94", "99.9%", "ALLOW");
  replaceText(presentation, "sh/nmt8ry1k", "핵심 API 성공률", "읽기·검색 자동 허용");
  replaceText(presentation, "sh/mlk7yt0z", "요청 유실과 dropped iteration까지 확인", "wiki_search · wiki_content_read");
  replaceText(presentation, "sh/9obqt8jq", "800ms", "APPROVE");
  replaceText(presentation, "sh/8n2p03i5", "핵심 조회 p99", "쓰기·ingest 사람 승인");
  replaceText(presentation, "sh/zit8ny1o", "탐색 흐름의 꼬리 지연 상한", "wiki_content_write · wiki_ingest");
  replaceText(presentation, "sh/yh07ut03", "1.5s", "DENY");
  replaceText(presentation, "sh/lkbqp8ju", "핵심 쓰기 p99", "공간·설정 변경 차단");
  replaceText(presentation, "sh/0j2pw3i9", "트랜잭션과 후속 처리 비용 반영", "미분류 도구도 default-deny");
  replaceText(presentation, "sh/id4r6d07", "10분 이상 지속", "레지스트리 SSOT");
  replaceText(presentation, "sh/el8jelor", "동일 인프라·데이터", "Bearer 인증");
  replaceText(presentation, "sh/fm1knqpc", "개방형 도착률", "Secret reference만");
  replaceText(presentation, "sh/gna1gv6x", "회복 시간 30초", "n8n 비활성");
  replaceText(presentation, "sh/1oj2p07i", "부하 종료 후 오류율과 p99가 30초 연속 SLO를 만족할 때 회복으로 판정", "새 MCP 서버가 추가돼도 같은 allow / approve / deny 경계를 적용");
  setSources(presentation.slides.getItem(18), [
    "config/mcp-registry.yaml — allow/approve/deny tiers, default-deny, secret_ref",
    "docs/mcp-registry.md — 사람 승인 흐름과 도구 정책 계약",
    "compose.ec2.yaml — bearer-protected mcp-proxy",
  ]);

  // Slide 20 — git durability and retry boundary.
  replaceText(presentation, "sh/yxgfy1kr", "PROJECT · CLUVERSE", "CASE 02 · GIT DURABILITY");
  replaceText(presentation, "sh/h0vq1s7i", "학교의 벽보다 관심사의 연결을 먼저 설계했다", "push 실패가 서비스 중단이나 지식 유실로 번지지 않게 했다");
  replaceText(presentation, "sh/7ad8vypg", "02", "20");
  replaceText(presentation, "sh/m9k7mdov", "전국 대학생이 학과·관심사로 모이고, 모집에서 실제 협업까지 이어지는 커뮤니티다.", "MCP 쓰기와 원격 Git 동기화를 분리하고, 실패한 커밋은 다음 주기까지 로컬에 남겼다.");
  replaceText(presentation, "sh/9cvqx876", "관심사·학과\n보드", "MCP write");
  replaceText(presentation, "sh/8bmpo361", "모집·지원", "wiki-data volume");
  replaceText(presentation, "sh/r6x872pk", "그룹 운영", "sidecar commit·rebase");
  replaceText(presentation, "sh/65oryxoz", "스파이크에서도\n읽기 흐름 보호", "team-wiki-v2\n실패 시 로컬 보존");
  replaceText(presentation, "sh/729wbql8", "기술 목표", "복구 경계");
  replaceText(presentation, "sh/kzix0b2x", "사람이 몰려도 핵심 조회·쓰기의 성공률과 tail latency가 무너지지 않는 구조", "origin 멱등 설정 · 충돌 cycle skip · clean tree의 미push commit도 재시도");
  replaceText(presentation, "sh/l0re9g32", "개인 프로젝트 · 2026.01–2026.07", "named volume + compose sidecar · 기본 120초 주기");
  setSources(presentation.slides.getItem(19), [
    "compose.ec2.yaml — wiki-data-sync boot wiring, commit/rebase/push loop, retry behavior",
    "docs/wiki-data-repo.md — named volume + compose sidecar 운영 모델",
    "git commits 05fe9e5, 68c7edc, 98ad51f — origin 멱등성과 deploy-key newline 결함 수정",
  ]);

  // Slide 21 — combined synthesis.
  replaceText(presentation, "sh/4vipwr2x", "경계를 바꾸고,\n남는 위험을 측정한다", "경계를 바꾸고,\n운영 가능한 구조를 만든다");
  replaceText(presentation, "sh/upgnqhkv", "증상과 성공 기준을 먼저 고정", "성공 기준과 원본 경계를 먼저 고정");
  replaceText(presentation, "sh/wri5s721", "대기·경합·내구성 비용을 분리", "실패 전파·권한·동기화 비용을 분리");
  replaceText(presentation, "sh/m1gnmxkz", "격벽·보상·폴백의 대가까지 검증", "남는 위험을 로그·테스트·런북으로 검증");
  replaceText(presentation, "sh/7e50zap0", "남은 과제", "다음 검증");
  replaceText(presentation, "sh/6dwzq58f", "외부 보강 작업의 Outbox 전환 · Redis 내구성/체크포인트 운영 · 업로드 규모 증가 시 비동기 접수와 backpressure 비교", "LLM Wiki ingest 품질 지표 · Git 백업 RTO/RPO · 쓰기 승인 흐름 자동화");
  setSources(presentation.slides.getItem(20), [
    "Portfolio synthesis based on the Cluverse case study and repository-grounded LLM Wiki Platform slides 16-20.",
  ]);

  for (const [index, slide] of presentation.slides.items.entries()) {
    const stem = `slide-${String(index + 1).padStart(2, "0")}`;
    await saveBlob(`${previewDir}/${stem}.png`, await presentation.export({ slide, format: "png", scale: 1 }));
    const layout = await slide.export({ format: "layout" });
    await fs.writeFile(`${layoutDir}/${stem}.layout.json`, await layout.text());
  }

  await saveBlob(`${buildDir}/final-montage.webp`, await presentation.export({ format: "webp", montage: true, scale: 1 }));
  const inspection = await presentation.inspect({
    kind: "slide,textbox,shape,image,table,chart,notes,layout",
    maxChars: 120000,
  });
  await fs.writeFile(`${buildDir}/final-inspect.ndjson`, inspection.ndjson);

  const pptx = await PresentationFile.exportPptx(presentation);
  await pptx.save(outputPath);
  console.log(outputPath);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
