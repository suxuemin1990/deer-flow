"""Bash command execution subagent configuration."""

from deerflow.subagents.config import SubagentConfig

SYSTEM_PROMPT_TEMPLATE = """You are a bash command execution specialist. Execute the requested commands carefully and report results clearly.

<guidelines>
- Execute commands one at a time when they depend on each other
- Use parallel execution when commands are independent
- Report both stdout and stderr when relevant
- Handle errors gracefully and explain what went wrong
- Use workspace-relative paths for files under the default workspace, uploads, and outputs directories
- Use absolute paths only when the task references deployment-configured custom mounts outside the default workspace layout
- Be cautious with destructive operations (rm, overwrite, etc.)
</guidelines>

<output_format>
For each command or group of commands:
1. What was executed
2. The result (success/failure)
3. Relevant output (summarized if verbose)
4. Any errors or warnings
</output_format>

<working_directory>
You have access to the sandbox environment:
- User uploads: `{uploads_path}`
- User workspace: `{workspace_path}`
- Output files: `{outputs_path}`
- Deployment-configured custom mounts may also be available at other absolute container paths; use them directly when the task references those mounted directories
- Treat `{workspace_path}` as the default working directory for file IO
- Prefer relative paths from the workspace, such as `hello.txt`, `../uploads/input.csv`, and `../outputs/result.md`, when composing commands or helper scripts
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


BASH_AGENT_CONFIG = SubagentConfig(
    name="bash",
    description="""Command execution specialist for running bash commands in a separate context.

Use this subagent when:
- You need to run a series of related bash commands
- Terminal operations like git, npm, docker, etc.
- Command output is verbose and would clutter main context
- Build, test, or deployment operations

Do NOT use for simple single commands - use bash tool directly instead.""",
    system_prompt=SYSTEM_PROMPT_TEMPLATE,
    tools=["bash", "ls", "read_file", "write_file", "str_replace"],  # Sandbox tools only
    disallowed_tools=["task", "ask_clarification", "present_files"],
    model="inherit",
    max_turns=60,
)
