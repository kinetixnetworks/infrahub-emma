#!/bin/bash
set -e

# Authenticate Claude Code by writing credentials directly.
# CLAUDE_CREDENTIALS should be the base64-encoded contents of ~/.claude/.credentials.json
# from an authenticated machine.
#
# To get this value, run on an authenticated machine:
#   cat ~/.claude/.credentials.json | base64 -w0
#
if [ -n "$CLAUDE_CREDENTIALS" ]; then
    echo "Writing Claude Code credentials..."
    mkdir -p /root/.claude
    echo "$CLAUDE_CREDENTIALS" | base64 -d > /root/.claude/.credentials.json
    chmod 600 /root/.claude/.credentials.json
    echo "Claude Code credentials configured."
else
    echo "WARNING: CLAUDE_CREDENTIALS not set. AI features (Schema Builder, Query Builder, Template Builder) will not work."
    echo ""
    echo "To authenticate, run on a machine where Claude Code is already logged in:"
    echo "  cat ~/.claude/.credentials.json | base64 -w0"
    echo ""
    echo "Then pass the output as CLAUDE_CREDENTIALS env var:"
    echo "  docker run -e CLAUDE_CREDENTIALS=\"<base64-string>\" ..."
fi

# Start Streamlit
exec uv run streamlit run main.py --server.port=8501 --server.address=0.0.0.0
