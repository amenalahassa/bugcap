# MCP server image, mirroring the one Glama builds to check the server
# (https://glama.ai/mcp/servers/amenalahassa/bugcap). CI builds it on every push and
# drives `bugcap mcp-serve` inside it (scripts/docker_smoke.py), so a release that
# would not start on Glama fails before it reaches PyPI.
#
#   docker build -t bugcap-mcp .
#   docker run -it --rm -e MCP_PROXY_DEBUG=true bugcap-mcp
FROM debian:trixie-slim
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && curl -fsSL https://deb.nodesource.com/setup_26.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g mcp-proxy@6.7.16 \
    && curl -LsSf https://astral.sh/uv/install.sh | UV_INSTALL_DIR="/usr/local/bin" sh \
    && uv python install 3.12 --default --preview \
    && apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*
WORKDIR /app
COPY . .
RUN uv sync --frozen --extra mcp
CMD ["mcp-proxy", "--", "/app/.venv/bin/bugcap", "mcp-serve"]
