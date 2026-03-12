# TODO: Make python version an arg
FROM docker.io/python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Env variables for the build
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# Install libraries and packages (including Node.js for Claude Code CLI)
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install --no-install-recommends -y curl git pkg-config build-essential ca-certificates && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install --no-install-recommends -y nodejs && \
    apt-get autoremove -y && \
    apt-get clean all && \
    rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Copy lock and install all dependencies
WORKDIR /source
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy application and install it
COPY . ./
RUN uv sync --frozen --no-dev

# Make entrypoint executable
RUN chmod +x /source/entrypoint.sh

# Run streamlit app
EXPOSE 8501
HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health
ENTRYPOINT ["/source/entrypoint.sh"]
