FROM debian:trixie-slim
ARG LLM_WIKI_VERSION=0.4.1
RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates curl git tar \
  && arch="$(dpkg --print-architecture)" \
  && case "$arch" in \
    amd64) target="x86_64-unknown-linux-gnu" ;; \
    arm64) target="aarch64-unknown-linux-gnu" ;; \
    *) echo "unsupported architecture: $arch" >&2; exit 1 ;; \
  esac \
  && curl -fsSL -o /tmp/llm-wiki.tar.gz "https://github.com/geronimo-iia/llm-wiki/releases/download/v${LLM_WIKI_VERSION}/${target}.tar.gz" \
  && tar xzf /tmp/llm-wiki.tar.gz -C /tmp \
  && install -m 0755 /tmp/llm-wiki /usr/local/bin/llm-wiki \
  && rm -f /tmp/llm-wiki /tmp/llm-wiki.tar.gz \
  && rm -rf /var/lib/apt/lists/*
COPY docker/llm-wiki-entrypoint.sh /usr/local/bin/llm-wiki-entrypoint.sh
RUN chmod +x /usr/local/bin/llm-wiki-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/llm-wiki-entrypoint.sh"]
CMD ["llm-wiki", "--config", "/config/config.toml", "serve", "--http", ":18765", "--watch"]
