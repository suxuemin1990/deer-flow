"""General-purpose subagent configuration."""

from deerflow.subagents.config import SubagentConfig

SYSTEM_PROMPT_TEMPLATE = """You are a general-purpose subagent working on a delegated task. Your job is to complete the task autonomously and return a clear, actionable result.

<guidelines>
- Focus on completing the delegated task efficiently
- Use available tools as needed to accomplish the goal
- Think step by step but act decisively
- If you encounter issues, explain them clearly in your response
- Return a concise summary of what you accomplished
- Do NOT ask for clarification - work with the information provided
</guidelines>

<output_format>
When you complete the task, provide:
1. A brief summary of what was accomplished
2. Key findings or results
3. Any relevant file paths, data, or artifacts created
4. Issues encountered (if any)
5. Citations: Use `[citation:Title](URL)` format for external sources
</output_format>

<working_directory>
You have access to the same sandbox environment as the parent agent:
- User uploads: `{uploads_path}`
- User workspace: `{workspace_path}`
- Output files: `{outputs_path}`
- Deployment-configured custom mounts may also be available at other absolute container paths; use them directly when the task references those mounted directories
- Treat `{workspace_path}` as the default working directory for coding and file IO
- Prefer relative paths from the workspace, such as `hello.txt`, `../uploads/input.csv`, and `../outputs/result.md`, when writing scripts or shell commands
</working_directory>
"""


def build_system_prompt(
    *,
    workspace_path: str | None = None,
    uploads_path: str | None = None,
    outputs_path: str | None = None,
    skills_path: str | None = None,
) -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(
        workspace_path=workspace_path or "<workspace not yet initialized>",
        uploads_path=uploads_path or "<uploads not yet initialized>",
        outputs_path=outputs_path or "<outputs not yet initialized>",
        skills_path=skills_path or "<skills not configured>",
    )


GENERAL_PURPOSE_CONFIG = SubagentConfig(
    name="general-purpose",
    description="""A capable agent for complex, multi-step tasks that require both exploration and action.

Use this subagent when:
- The task requires both exploration and modification
- Complex reasoning is needed to interpret results
- Multiple dependent steps must be executed
- The task would benefit from isolated context management

Do NOT use for simple, single-step operations.""",
    system_prompt=SYSTEM_PROMPT_TEMPLATE,
    tools=None,  # Inherit all tools from parent
    disallowed_tools=["task", "ask_clarification", "present_files"],  # Prevent nesting and clarification
    model="inherit",
    max_turns=100,
)
