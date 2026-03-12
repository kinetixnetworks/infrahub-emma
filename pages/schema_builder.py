import datetime
import json
import re
from typing import Any

import streamlit as st
import yaml

from emma.assistant_utils import generate_yaml
from emma.claude_utils import ClaudeCodeError, invoke_claude_with_history
from emma.infrahub import check_schema, get_cached_schema
from emma.streamlit_utils import handle_reachability_error, set_page_config
from menu import menu_with_redirect

SCHEMA_BUILDER_SYSTEM_PROMPT = """You are Emma, an expert Infrahub schema builder assistant.
You help users create and modify infrastructure schemas in YAML format for the Infrahub platform.

When generating schemas, follow these rules:
- Output valid YAML schema definitions compatible with Infrahub
- Use proper Infrahub schema structure with nodes, generics, attributes, and relationships
- Include appropriate namespaces, labels, and descriptions
- Always output schemas in a single fenced code block (```yaml ... ```)
- Include a comment on the first line of the code block with a suggested filename (e.g. # interfaces.yml)
- Be concise in explanations but thorough in schema definitions
"""

INITIAL_PROMPT_HEADER = """The following is a user request for a new schema, or a modification.
You are to generate a new schema segment that will work with the provided existing schema.

Here is an overview of the nodes present, in `namespace: [node: [attribute: kind]]` format.

This is *not* the format we want back, just an idea of what is here already.

```yml
{overview}
```

User request:
```
"""

ERROR_PROMPT = """We've generated the following schema, but when validating with Infrahub we ran into some problems.
Regenerate the schema so that it will pass our checks.

Schema:
```yml
{schema}
```

Errors:
```
{errors}
"""

FILENAME_PROMPT_FOOTER = """```\n\nYou should send schemas in one code block,
with a comment on the first line with a filename.

Something like '# interfaces.yml` is ideal (based on the content of the schema)"""


def transform_schema(schema_dict: dict[str, Any]) -> dict[str, Any]:
    """Transform a schema dictionary into a simplified format."""
    transformed: dict[str, Any] = {
        "name": schema_dict["name"],
        "namespace": schema_dict["namespace"],
        "label": schema_dict["label"],
        "description": schema_dict["description"],
        "default_filter": schema_dict.get("default_filter"),
        "human_friendly_id": schema_dict.get("human_friendly_id"),
        "attributes": [],
        "relationships": [],
    }

    for attr in schema_dict["attributes"]:
        transformed["attributes"].append(
            {
                "name": attr["name"],
                "kind": attr["kind"],
                "unique": attr.get("unique", False),
                "optional": attr.get("optional", False),
            }
        )

    for rel in schema_dict["relationships"]:
        transformed["relationships"].append(
            {
                "name": rel["name"],
                "peer": rel["peer"],
                "cardinality": rel["cardinality"],
                "kind": rel["kind"],
                "optional": rel.get("optional", False),
            }
        )

    return transformed


def transform_schema_overview(schema_dict: dict[str, Any]) -> dict[str, Any]:
    """Transform a schema dictionary into an overview format."""
    overview: dict[str, Any] = {}
    namespace = schema_dict["namespace"]

    if namespace not in overview:
        overview[namespace] = {}

    node_name = schema_dict["name"]
    overview[namespace][node_name] = {}

    # Add attributes with their kinds
    for attr in schema_dict["attributes"]:
        overview[namespace][node_name][attr["name"]] = attr["kind"]

    return overview


def merge_overviews(overview_list: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge multiple schema overviews into one."""
    merged: dict[str, Any] = {}
    for overview in overview_list:
        for namespace, nodes in overview.items():
            if namespace not in merged:
                merged[namespace] = {}
            for node_name, attrs in nodes.items():
                if node_name not in merged[namespace]:
                    merged[namespace][node_name] = {}
                merged[namespace][node_name].update(attrs)
    return merged


def translate_errors(schema_errors: list[dict[str, Any]]) -> str:
    human_readable = []
    for error in schema_errors:
        if "loc" in error:
            location = " -> ".join(map(str, error["loc"][3:]))
            err_message = error["msg"]
            input_value = error["input"]
            human_readable.append(
                f"{err_message}\n\nLocation: {location}\n\nInput:\n```json\n{json.dumps(input_value, indent=2)}\n```"
            )
        else:
            err_message = error["message"]
            err_code = error["extensions"]["code"]
            human_readable.append(f"Error Message: {err_message}\n\n\tCode: {err_code}\n")
    return "\n\n".join(human_readable)


if "messages" not in st.session_state:
    st.session_state.messages = []

if "check_schema_errors" not in st.session_state:
    st.session_state.check_schema_errors = "Placeholder"

buttons_disabled = not st.session_state.messages

set_page_config(title="Schema Builder")
st.markdown("# Schema Builder")
menu_with_redirect()

yaml_buffer = generate_yaml(st.session_state.messages)

if st.sidebar.download_button(
    label="Export Conversation",
    data=yaml_buffer,
    file_name=f"schema_generator_log_{datetime.datetime.now(tz=datetime.timezone.utc)}.md",
    mime="text/markdown",
    disabled=buttons_disabled,
):
    pass


if st.sidebar.button("New Chat", disabled=buttons_disabled):
    st.session_state.messages = []
    st.rerun()

if "infrahub_schema_context" not in st.session_state:
    infrahub_schema = get_cached_schema(st.session_state.infrahub_branch)
    if not infrahub_schema:
        handle_reachability_error()
    else:
        transformed_schema = {
            k: transform_schema(v.model_dump())
            for k, v in infrahub_schema.items()
            if v.namespace  # not in ("Core", "Profile", "Builtin")
        }

        # Store the schema YAML as context for Claude
        st.session_state.infrahub_schema_yaml = yaml.dump(transformed_schema, default_flow_style=False)
        st.session_state.infrahub_schema_context = True

        # Create and store the schema overview for the initial prompt
        overviews = [transform_schema_overview(schema.model_dump()) for schema in infrahub_schema.values()]
        st.session_state.schema_overview = merge_overviews(overviews)

demo_prompts = [
    "Generate a schema for kubernetes. It must contain Cluster, Node, Namespace.",
    "Build a DNS record schema, with a dropdown for record types.",
    "Come up with a simple schema for NTP.",
]

if not st.session_state.messages:
    # Add buttons for demo prompts
    st.markdown("### Try me!")

    for demo in demo_prompts:
        if st.button(demo):
            st.session_state.prompt_input = demo

    st.markdown("Or enter a message below to start.")


prompt = st.chat_input("What is up?")

# Set the input field
if "prompt_input" in st.session_state:
    prompt = st.session_state.prompt_input
    del st.session_state.prompt_input

# Display previous messages
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Handle new user input
if prompt:
    # Build the actual prompt with context for the first message
    actual_prompt = prompt
    if not st.session_state.messages:
        actual_prompt = (
            INITIAL_PROMPT_HEADER.format(overview=st.session_state.schema_overview)
            + prompt
            + FILENAME_PROMPT_FOOTER
        )

    st.session_state.messages.append({"role": "user", "content": actual_prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner(text="Thinking! Just a moment..."):
            try:
                # Provide the full schema as a context file
                context_files = {}
                if "infrahub_schema_yaml" in st.session_state:
                    context_files["current_schema.yaml"] = st.session_state.infrahub_schema_yaml

                response = invoke_claude_with_history(
                    messages=st.session_state.messages,
                    system_prompt=SCHEMA_BUILDER_SYSTEM_PROMPT,
                    context_files=context_files if context_files else None,
                )
                output = response["output"]
            except ClaudeCodeError as exc:
                output = f"Error communicating with Claude: {exc}"

        st.write(output)

    st.session_state.messages.append({"role": "assistant", "content": output})

    st.session_state.combined_code = "\n\n".join(re.findall(r"```(?:\w+)?(.*?)```", output, re.DOTALL)).lstrip("\n")

    # Rerun to enable schema check/fix buttons
    st.rerun()

col1, col2, col3 = st.columns([2, 2, 2])

# Check Schema button
with col1:
    if st.button(
        "Check Schema",
        disabled=buttons_disabled or st.session_state.messages[-1]["role"] == "ai",
        help="Check the schema with your Infrahub instance",
    ):
        assistant_messages = [m for m in st.session_state.messages if m["role"] == "assistant"]

        schema_check_result = check_schema(
            branch=st.session_state.infrahub_branch, schemas=[yaml.safe_load(st.session_state.combined_code)]
        )
        if schema_check_result:
            if schema_check_result.success:
                message = "Schema is valid!\n\nWant to download it, or check it out in the importer?"
                st.session_state.check_schema_errors = False  # Clear any previous errors

            elif schema_check_result.response:
                errors = schema_check_result.response.get("errors")

                # Sometimes the schema will fail to parse at all (like if extensions is an empty list)
                if not errors:
                    errors = schema_check_result.response.get("detail")

                errors_out = translate_errors(schema_errors=errors)
                st.session_state.schema_errors = errors_out  # Store errors in session state

                message = "Hmm, looks like we've got some problems.\n\n" + errors_out

            else:
                message = "Schema check completed with an unexpected result."

            # We use 'ai' as the role here to format the message the same as assistant messages,
            # But not include them in the messages we look for schema in.
            st.session_state.messages.append({"role": "ai", "content": message})
            st.rerun()


if st.session_state.get("combined_code"):
    code = st.session_state.combined_code.splitlines()

    if code[0].lstrip().startswith("#"):
        filename = code[0].replace("#", "").lstrip()
        code = "\n".join(code[1:])

    else:
        filename = f"schema_generated_{str(datetime.datetime.now(tz=datetime.timezone.utc))[:16]}.yml"
        code = "\n".join(code)

    with col2:
        st.download_button(
            label="Download Schema",
            data=code,
            file_name=filename,
            mime="text/yaml",
        )

    with col3:
        if not st.session_state.check_schema_errors:
            if st.button("See in Schema Importer"):
                st.session_state.generated_files = [{"name": filename, "content": st.session_state.combined_code}]

                st.switch_page("pages/schema_loader.py")

with col1:
    if st.session_state.get("schema_errors"):
        if st.button("Fix Schema", help="Send the generated schema and errors to our schema builder"):
            st.session_state.prompt_input = ERROR_PROMPT.format(
                errors=st.session_state.schema_errors, schema=st.session_state.combined_code
            )
            st.session_state.schema_errors = False
            st.rerun()  # Force rerun to handle new prompt input
