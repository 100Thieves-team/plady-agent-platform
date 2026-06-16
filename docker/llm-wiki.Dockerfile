FROM rust:1-bookworm AS builder
WORKDIR /src
COPY llm-wiki/ ./
RUN cargo build --release --locked

FROM debian:bookworm-slim
RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates git \
  && rm -rf /var/lib/apt/lists/*
COPY --from=builder /src/target/release/llm-wiki /usr/local/bin/llm-wiki
COPY docker/llm-wiki-entrypoint.sh /usr/local/bin/llm-wiki-entrypoint.sh
RUN chmod +x /usr/local/bin/llm-wiki-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/llm-wiki-entrypoint.sh"]
CMD ["llm-wiki", "--config", "/config/config.toml", "serve", "--http", ":18765", "--watch"]
