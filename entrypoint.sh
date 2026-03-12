#!/bin/bash
set -e

# Authenticate Claude Code with a subscription token if provided
if [ -n "$CLAUDE_AUTH_TOKEN" ]; then
    echo "Authenticating Claude Code with provided token..."
    echo "$CLAUDE_AUTH_TOKEN" | claude setup-token 2>&1 || {
        echo "WARNING: Claude Code authentication failed. AI features will not work."
    }
else
    echo "WARNING: CLAUDE_AUTH_TOKEN not set. AI features (Schema Builder, Query Builder, Template Builder) will not work."
    echo "To authenticate, run 'claude setup-token' locally and pass the token via CLAUDE_AUTH_TOKEN env var."
fi

# Start Streamlit
exec uv run streamlit run main.py --server.port=8501 --server.address=0.0.0.0
