<!-- markdownlint-disable -->
![Infrahub Logo](https://assets-global.website-files.com/657aff4a26dd8afbab24944b/657b0e0678f7fd35ce130776_Logo%20INFRAHUB.svg)
<!-- markdownlint-restore -->

# Infrahub by OpsMill

[Infrahub](https://github.com/opsmill/infrahub) by [OpsMill](https://opsmill.com) acts as a central hub to manage the data, templates and playbooks that powers your infrastructure. At its heart, Infrahub is built on 3 fundamental pillars:

- **A Flexible Schema**: A model of the infrastructure and the relation between the objects in the model, that's easily extensible.
- **Version Control**: Natively integrated into the graph database which opens up some new capabilities like branching, diffing, and merging data directly in the database.
- **Unified Storage**: By combining a graph database and git, Infrahub stores data and code needed to manage the infrastructure.

## Emma

Emma is an experimental agent originally developed by [OpsMill](https://opsmill.com) for their [Infrahub](https://github.com/opsmill/infrahub) platform. This fork is maintained by **Josh Finlay** at **[Kinetix Networks](https://kinetixnetworks.com.au)** and integrates [Claude Code](https://docs.anthropic.com/en/docs/claude-code) by Anthropic as the AI backend, replacing the original OpenAI-based implementation.

Currently, Emma can help you to:

- Import CSV Data into Infrahub
- Export Data from Infrahub in CSV format
- Build, Load, and Visualize the Infrahub schema
- Generate schemas from natural language using AI (Schema Builder)
- Build GraphQL queries with AI assistance (Query Builder)
- Create Jinja2 templates from query data with AI (Template Builder)

![Home page](static/home_page.png)

## Prerequisites

- Python 3.10–3.12
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and on your PATH
- A [Claude Pro or Max subscription](https://claude.ai) (for AI-powered features)

## Setting Up Claude Code

Emma uses the Claude Code CLI binary for its AI features. You need to authenticate once before using the Schema Builder, Query Builder, or Template Builder.

### Local Development

1. Install Claude Code:

   ```bash
   npm install -g @anthropic-ai/claude-code
   ```

2. Authenticate with your Claude subscription:

   ```bash
   claude setup-token
   ```

   Follow the prompts to log in with your Claude.ai account.

3. Run Emma:

   ```bash
   uv sync
   uv run streamlit run main.py
   ```

### Docker

When running Emma in Docker, pass your Claude authentication token as an environment variable.

1. First, get your token by running locally:

   ```bash
   claude setup-token
   ```

2. Run with Docker Compose:

   ```bash
   CLAUDE_AUTH_TOKEN="<your-token>" docker-compose up
   ```

   Or create a `.env` file next to `docker-compose.yml`:

   ```env
   CLAUDE_AUTH_TOKEN=<your-token>
   ```

   The container's entrypoint will automatically authenticate Claude Code before starting the app. If no token is provided, Emma will still run but the AI-powered features (Schema Builder, Query Builder, Template Builder) will not be available.

## Running Emma

Documentation for using Emma is available in the [Emma documentation](https://docs.infrahub.app/emma/).
