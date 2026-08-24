# llm-wiki 는 vendored 소스(llm-wiki/)에서 빌드한다.
#
# 예전에는 upstream 릴리스 tarball(v0.4.1)을 내려받았는데, 그러면 이 저장소의
# llm-wiki/ 수정이 이미지에 절대 반영되지 않는다 (2026-08-24 에 MCP asset
# read/write 패치가 배포돼도 동작하지 않아 드러난 문제). 소스가 곧 배포물이
# 되도록 멀티스테이지 빌드로 바꿨다. vendored 트리는 upstream v0.4.1 + 로컬 패치.
FROM rust:1.95-slim-trixie AS builder
WORKDIR /build
RUN apt-get update \
  && apt-get install -y --no-install-recommends pkg-config libssl-dev \
  && rm -rf /var/lib/apt/lists/*
# 의존성 레이어를 먼저 굳혀 소스만 바뀌었을 때 재컴파일 범위를 줄인다.
COPY llm-wiki/Cargo.toml llm-wiki/Cargo.lock llm-wiki/rust-toolchain.toml ./
RUN mkdir -p src \
  && echo 'fn main() {}' > src/main.rs \
  && : > src/lib.rs \
  && cargo build --release --locked \
  && rm -rf src target/release/llm-wiki target/release/deps/llm_wiki* \
       target/release/deps/libllm_wiki*
COPY llm-wiki/ ./
RUN cargo build --release --locked --bin llm-wiki

FROM debian:trixie-slim
# git 은 llm-wiki 가 ingest 시 커밋할 때 쓴다. curl/tar 는 릴리스를 내려받던
# 시절의 잔재라 뺐다.
RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates git \
  && rm -rf /var/lib/apt/lists/*
COPY --from=builder /build/target/release/llm-wiki /usr/local/bin/llm-wiki
COPY docker/llm-wiki-entrypoint.sh /usr/local/bin/llm-wiki-entrypoint.sh
RUN chmod +x /usr/local/bin/llm-wiki-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/llm-wiki-entrypoint.sh"]
CMD ["llm-wiki", "--config", "/config/config.toml", "serve", "--http", ":18765", "--watch"]
