import datetime
import json
import re
from typing import Any

import streamlit as st
import yaml
from infrahub_sdk.exceptions import GraphQLError

from emma.assistant_utils import generate_yaml
from emma.claude_utils import ClaudeCodeError, invoke_claude_with_history
from emma.gql_queries import get_gql_schema
from emma.infrahub import run_gql_query
from emma.streamlit_utils import handle_reachability_error, set_page_config
from menu import menu_with_redirect


def remove_extra_values(d: Any) -> Any:
    if isinstance(d, dict):
        schema_key = "__schema"
        if schema_key in d:
            return {schema_key: remove_extra_values(d[schema_key])}

        if d.get("isDeprecated") is False:
            del d["isDeprecated"]

        return {k: remove_extra_values(v) for k, v in d.items()}

    if isinstance(d, list):
        data = [obj for obj in d if isinstance(obj, dict) and "__" not in obj.get("name", "")]
        return [remove_extra_values(v) for v in data if v is not None]
    return d


QUERY_BUILDER_SYSTEM_PROMPT = """You are Emma, an expert GraphQL query builder for the Infrahub platform.
You help users create GraphQL queries to retrieve data from their Infrahub instance.

When generating queries, follow these rules:
- Output valid GraphQL queries compatible with Infrahub
- Use proper Infrahub query structure with edges, nodes, and attribute value access
- Always output queries in a single fenced code block (```graphql ... ```)
- Be concise in explanations but thorough in query definitions
- DO NOT include internal attributes like: is_default, is_inherited, is_protected, is_visible, updated_at, id, is_from_profile
  unless the user specifically requests them
- Use fragments to conditionally fetch extra data where present
- Keep queries concise without extra data outside of the user's request
"""

INITIAL_PROMPT = """\n\nThe above is the user requirements spec!

Based on the GraphQL schema provided as context, build a query that matches the user's needs.

Do NOT include internal attributes like:
is_default, is_inherited, is_protected, is_visible, updated_at, id, is_from_profile
unless the user specifically requests internal attributes.

Your query needs to be concise, and without any extra data outside of the users query."""

ERROR_PROMPT = """We've generated the following query, but when running it against Infrahub we ran into some problems.
Regenerate the query so that it will work.

Query:
```gql
{query}
```

Errors:
```
{errors}
```"""

# Set Streamlit page configuration
set_page_config(title="Query Builder")

# Initialize session state
if "query_messages" not in st.session_state:
    st.session_state.query_messages = []

buttons_disabled = not st.session_state.query_messages

# UI Elements
st.markdown("# Query Builder")
menu_with_redirect()

# Sidebar for exporting conversation and starting a new chat
yaml_buffer = generate_yaml(st.session_state.query_messages)
st.sidebar.download_button(
    label="Export Conversation",
    data=yaml_buffer,
    file_name=f"query_builder_log_{datetime.datetime.now(tz=datetime.timezone.utc)}.yml",
    mime="text/markdown",
    disabled=buttons_disabled,
)

if st.sidebar.button("New Chat", disabled=buttons_disabled):
    if "prompt_input" in st.session_state:
        del st.session_state.prompt_input

    st.session_state.query_messages = []

    st.rerun()

# Fetch GraphQL schema
if "infrahub_query_schema_context" not in st.session_state:
    with st.spinner(text="Processing the schema! Just a second."):
        gql_schema = get_gql_schema(st.session_state.infrahub_branch)

        if not gql_schema:
            handle_reachability_error()

        else:
            clean_schema = remove_extra_values(gql_schema)

            yaml_schema = yaml.dump(clean_schema, default_flow_style=False)

            # Store the schema YAML as context for Claude
            st.session_state.infrahub_query_schema_yaml = yaml_schema
            st.session_state.infrahub_query_schema_context = True

# Demo prompts
demo_prompts = [
    "I need a query to grab all the info available to template VRF configs.",
    "Can you show a helpful IPAM query for getting started?",
    "How would I query ip prefixes per location? And filter by location?",
]

if not st.session_state.query_messages:
    st.markdown("### Try me!")
    for demo in demo_prompts:
        if st.button(demo):
            st.session_state.prompt_input = demo
    st.markdown("Or enter a message below to start.")

# Handle user input
prompt = st.chat_input("What is up?")
if "prompt_input" in st.session_state:
    prompt = st.session_state.prompt_input
    del st.session_state.prompt_input

for message in st.session_state.query_messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt:
    # Build the actual prompt with context for the first message
    actual_prompt = prompt
    if not st.session_state.query_messages:
        actual_prompt = prompt + INITIAL_PROMPT

    st.session_state.query_messages.append({"role": "user", "content": actual_prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner(text="Thinking! Just a moment..."):
            try:
                # Provide the GraphQL schema as a context file
                context_files = {}
                if "infrahub_query_schema_yaml" in st.session_state:
                    context_files["graphql_schema.yaml"] = st.session_state.infrahub_query_schema_yaml

                response = invoke_claude_with_history(
                    messages=st.session_state.query_messages,
                    system_prompt=QUERY_BUILDER_SYSTEM_PROMPT,
                    context_files=context_files if context_files else None,
                )
                output = response["output"]
            except ClaudeCodeError as exc:
                output = f"Error communicating with Claude: {exc}"

        st.write(output)

    st.session_state.query_messages.append({"role": "assistant", "content": output})
    st.session_state.combined_code = "\n\n".join(re.findall(r"```graphql(.*?)```", output, re.DOTALL)).lstrip("\n")
    st.rerun()

col1, col2, col3 = st.columns([2, 2, 2])

# Check query button
with col1:
    if st.button(
        "Check query",
        disabled=buttons_disabled or st.session_state.query_messages[-1]["role"] == "ai",
        help="Check the query with your Infrahub instance",
    ):
        assistant_messages = [m for m in st.session_state.query_messages if m["role"] == "assistant"]
        try:
            query_check_result = run_gql_query(
                branch=st.session_state.infrahub_branch, query=st.session_state.combined_code
            )

            message = f"""Query is valid!

Here's a sample of your data:

```json
{json.dumps(query_check_result, indent=4)[:500]}...
```

Want to download it? Or refine it?"""

            st.session_state.check_query_errors = False

        except GraphQLError as e:
            st.session_state.query_errors = e.errors  # Store errors in session state

            message = "Hmm, looks like we've got some problems.\n\n```json" + json.dumps(e.errors, indent=4)

        st.session_state.query_messages.append({"role": "ai", "content": message})
        st.rerun()

if st.session_state.get("combined_code"):
    code = st.session_state.combined_code.splitlines()
    filename = (
        code[0].replace("#", "").lstrip()
        if code[0].lstrip().startswith("#")
        else f"query_generated_{str(datetime.datetime.now(tz=datetime.timezone.utc))[:16]}.gql"
    )
    code = "\n".join(code[1:] if filename != code[0] else code)

    with col2:
        st.download_button(
            label="Download query",
            data=code,
            file_name=filename,
            mime="text/gql",
        )

# Fix query button
with col1:
    if st.session_state.get("query_errors"):
        if st.button("Fix query", help="Send the generated query and errors to our query builder"):
            st.session_state.prompt_input = ERROR_PROMPT.format(
                errors=st.session_state.query_errors, query=st.session_state.combined_code
            )
            st.session_state.query_errors = False
            st.rerun()
