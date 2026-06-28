FROM debian:bookworm-slim
ARG HUGO_VERSION=0.147.0
RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates curl git \
  && arch="$(dpkg --print-architecture)" \
  && case "$arch" in \
    amd64) hugo_arch="amd64" ;; \
    arm64) hugo_arch="arm64" ;; \
    *) echo "unsupported architecture: $arch" >&2; exit 1 ;; \
  esac \
  && curl -fsSL -o /tmp/hugo.deb "https://github.com/gohugoio/hugo/releases/download/v${HUGO_VERSION}/hugo_extended_${HUGO_VERSION}_linux-${hugo_arch}.deb" \
  && apt-get install -y /tmp/hugo.deb \
  && rm -f /tmp/hugo.deb \
  && rm -rf /var/lib/apt/lists/*

# Bake the Hugo scaffold (layouts/assets/config) into the image so the EC2 origin
# needs no repo checkout. At runtime the container copies it into the shared
# /workspace/site directory, where Hugo's `../wiki` module mount resolves against
# the llm-wiki-managed content in /workspace/wiki. See compose.ec2.yaml.
COPY llm-wiki-hugo-cms/site /opt/site-template

WORKDIR /workspace/site
