# Smoke checklist — remove-sandbox-isolation

Date drafted: 2026-05-05
Plan: `docs/superpowers/plans/2026-05-05-remove-sandbox-isolation.md`
Spec: `docs/superpowers/specs/2026-05-05-remove-sandbox-isolation-design.md`
Diff window: `878be2b6..HEAD` (29 commits)
Mode: whole-plan

This refactor collapses a multi-backend sandbox (bwrap + AioSandbox + virtual `/mnt/*` paths) into a single host-direct `LocalSandbox`. Unit tests cover the seams (config schema, prompt template substitution, cwd plumbing, URL shape, middleware-chain absence), so this checklist focuses on the **cross-process / live-stack / UI-render** behaviour those tests cannot reach: an actual LLM thread driving an actual agent against a running gateway, frontend rendering against the new artifact URL shape, app boot loading legacy yaml, and end-to-end file flow upload → workspace → outputs → artifact link → browser.

## Spec gaps

None. The spec carries an explicit `## Contract surface` section (14 entries); every manual item below traces back to one of those entries plus the diff path that touched it.

---

## Required (P0)

### S1. Fresh chat thread can run `bash` with cwd defaulted to workspace_path

- **Category:** composition
- **Source:** Contract `local_sandbox.py:execute_command`, `sandbox/tools.py:bash_tool`. Diff: `80f63e38` (cwd parameter), `d4798548` (bash_tool reads `workspace_path`).
- **Path:**
  1. Open frontend `http://localhost:3000`, start a new chat thread.
  2. Send: `Run "pwd && ls -la" using the bash tool. Don't use any other tools.`
- **Evidence required:** copy/paste of the assistant's reply containing the bash output block.
- **Pass criterion:** stdout contains a path of the form `<base>/threads/<tid>/user-data/workspace` (the per-thread workspace) — **not** the gateway-process cwd, **not** `/mnt/user-data/workspace`.

### S2. Lead agent system prompt renders with real host paths (no `/mnt/*`)

- **Category:** cross-process
- **Source:** Contract `lead_agent/prompt.py`. Diff: `b1c79800`, `93ccf90b`.
- **Path:** in the same thread as S1 send: `Without using any tools, repeat verbatim the section of your system prompt that lists the workspace, uploads, outputs and skills directory paths.`
- **Evidence required:** the four paths it quotes back.
- **Pass criterion:** all four are absolute host paths (e.g. `/data/.../user-data/workspace`, `/data/src/deer-flow/skills`); the strings `/mnt/user-data` and `/mnt/skills` appear **zero** times in the reply.

### S3. Upload → uploads_path → agent reads file end-to-end

- **Category:** composition
- **Source:** Contract `uploads/manager.py:get_artifact_url`, `lead_agent/prompt.py` (uploads block via uploads_middleware).  Diff: `b91db157` (uploads router), `93ccf90b` (uploads_middleware), `cf352df5` (short URL).
- **Path:**
  1. In a fresh chat thread, attach a small text file (e.g. `note.txt` with content `hello-smoke-<random>`).
  2. Send: `Read the file I just uploaded with the read_file tool and tell me its contents verbatim.`
- **Evidence required:** assistant's reply quoting the random token.
- **Pass criterion:** the reply contains the random token; the agent issued `read_file` with an **absolute host path** under the thread's `uploads_path` (not `/mnt/user-data/uploads/note.txt`). Verify by inspecting the tool-call display in the UI.

### S4. Artifact link in chat opens with new short URL shape

- **Category:** ui-render
- **Source:** Contract `uploads/manager.py:get_artifact_url`, frontend artifact link rendering. Diff: `cf352df5`, `b91db157`.
- **Path:** in S3's thread, hover/inspect the chat bubble showing the uploaded file, copy the link target.
- **Evidence required:** the URL string + a screenshot (or DOM dump) of the link.
- **Pass criterion:** URL matches `/api/threads/<tid>/artifacts/uploads/<filename>` (no `mnt/user-data/` segment); clicking it returns 200 and renders the file inline.

### S5. Legacy `/mnt/user-data/...` artifact URL still resolves (back-compat)

- **Category:** cross-process
- **Source:** Contract artifact route accepts both shapes. Diff: `cf352df5`.
- **Path:** with the `<tid>` and `<filename>` from S4, run on the host:
  ```
  curl -i "http://localhost:8001/api/threads/<tid>/artifacts/mnt/user-data/uploads/<filename>"
  curl -i "http://localhost:8001/api/threads/<tid>/artifacts/uploads/<filename>"
  ```
- **Evidence required:** paste of both response status lines and `Content-Length`.
- **Pass criterion:** both return `200 OK` with identical `Content-Length`. The legacy form works; the new form works.

### S6. `present_file_tool` renders an outputs file as an inline artifact in the UI

- **Category:** ui-render + composition
- **Source:** Contract `present_file_tool` host paths under `outputs_path`. Diff: `73717a61`.
- **Path:** in a fresh thread send: `Use bash to write a one-line text file at <outputs_path>/smoke.txt containing "smoke-<random>", then call present_file with that absolute path.` (Replace `<outputs_path>` with the absolute path the agent quotes from S2 if asked.)
- **Evidence required:** screenshot of the chat showing the file artifact card + a `curl` of the artifact URL on the card.
- **Pass criterion:** the artifact card renders with filename `smoke.txt`; `curl` against its href returns 200 with the random token; the URL is the new short form (no `mnt/user-data/`).

### S7. Subagent dispatch receives template-substituted system prompt

- **Category:** composition
- **Source:** Contract `lead_agent/prompt.py` + diff `77c8ff7b` (general_purpose / bash_agent template vars), `prompt_resolver` module.
- **Path:** in a fresh thread send: `Dispatch a general_purpose subagent. Tell it to print its own system prompt and reply with just the lines that mention workspace/uploads/outputs/skills paths.`
- **Evidence required:** subagent's quoted prompt lines.
- **Pass criterion:** quoted lines contain absolute host paths; zero occurrences of literal `{workspace_path}`, `{uploads_path}`, `{outputs_path}`, `{skills_path}` placeholders, and zero `/mnt/*` substrings.

### S8. `bash_agent` subagent works (no `allow_host_bash` gate, no bwrap branch)

- **Category:** composition
- **Source:** Contract middleware chain has no SandboxMiddleware; bash works without gate. Diff: `2a7ff733`, `3f184d63`.
- **Path:** in a fresh thread send: `Dispatch a bash_agent subagent. Tell it to run "echo SMOKE_<random> && pwd" and report the exact output.`
- **Evidence required:** subagent's reply.
- **Pass criterion:** stdout contains `SMOKE_<random>` and a workspace-path `pwd` value; no error like "host bash disabled" or "bwrap not installed"; no SandboxError.

### S9. Backend boots on a config containing legacy `sandbox.use` and emits exactly one deprecation warning

- **Category:** cross-process
- **Source:** Contract `SandboxConfig` legacy compatibility. Diff: `a9b1089c` (warn hook), `5ff7ef69` (field deletion).
- **Path:**
  1. Edit local `config.yaml` (or env override) to add:
     ```
     sandbox:
       use: deerflow.community.aio_sandbox:AioSandboxProvider
       allow_host_bash: true
       image: ghcr.io/example/aio:latest
     ```
  2. Restart the gateway: `make dev` (or whichever target restarts uvicorn/langgraph).
  3. Capture stdout/stderr for the first 10 seconds of boot.
- **Evidence required:** grep of boot logs:
  ```
  grep -E "sandbox\.use|no longer supported|deprecat" <boot.log>
  ```
- **Pass criterion:** exactly **one** WARNING line containing `sandbox.use` and "no longer supported"; no ERROR; gateway `/health` returns 200; subsequent boot without the legacy field emits zero such warnings.

### S10. Frontend has no `/mnt/user-data` or `/mnt/skills` literal in shipped bundle

- **Category:** ui-render
- **Source:** Contract `frontend/src/...` artifact rendering. Diff: `8e2a95eb` (cosmetic literal change).
- **Path:** on the host:
  ```
  cd /data/src/deer-flow && grep -rn "/mnt/user-data\|/mnt/skills" frontend/src/ \
    --exclude-dir=node_modules --exclude-dir=.next
  ```
- **Evidence required:** paste of grep output (or "no matches").
- **Pass criterion:** zero matches. (The cosmetic landing-page literal must already have been replaced.)

### S11. Repo-wide grep: only legitimate `/mnt/*` literal is `/mnt/acp-workspace` inside the ACP tool

- **Category:** cross-process (final guarantee that the migration completed)
- **Source:** Contract entries 5, 13; spec §"Non-goals" carve-out for ACP. Diff: spans the whole refactor; `66935ec3` moved the ACP constant.
- **Path:**
  ```
  cd /data/src/deer-flow && grep -rn "/mnt/user-data\|/mnt/skills" \
    backend/packages backend/app frontend/src skills/ docs/superpowers/specs docs/superpowers/plans \
    README.md CONTRIBUTING.md \
    --exclude-dir=node_modules --exclude-dir=.next --exclude-dir=__pycache__ 2>/dev/null
  ```
  Then:
  ```
  grep -rn "/mnt/acp-workspace" backend/packages
  ```
- **Evidence required:** both greps' full output.
- **Pass criterion:** first grep returns **zero hits in production code** (hits inside `docs/superpowers/specs/` or `plans/` are acceptable as historical record — call them out explicitly if present); second grep shows the constant in `tools/builtins/invoke_acp_agent_tool.py` only (sandbox/tools.py must no longer carry it).

---

## Recommended (P1)

### S12. Skill end-to-end: a SKILL.md without `/mnt/*` literals still drives a successful tool run

- **Category:** composition
- **Source:** Contract `skills/public/*/SKILL.md` no `/mnt/*` literals + intra-skill relative paths. Diff: `9cebe658`.
- **Path:** start a thread; ask the agent to use the `image-generation` skill (or any skill in `skills/public/`) to perform a tiny task that requires the skill to invoke `./scripts/...` against `<UPLOADS_DIR>` / `<OUTPUTS_DIR>` placeholders.
- **Evidence required:** the tool-call trace + final artifact (or a clear error if the skill fails).
- **Pass criterion:** the agent resolves the placeholders against real paths and the script runs to completion; no `FileNotFoundError: /mnt/...` traceback.

### S13. ACP tool still references `/mnt/acp-workspace` internally and surfaces outputs via real host path

- **Category:** cross-process
- **Source:** Contract `invoke_acp_agent_tool.py`. Diff: `66935ec3`.
- **Path:** if the ACP container is part of the dev stack, dispatch an ACP agent task that produces an output file; otherwise inspect `invoke_acp_agent_tool.py` source for the constant.
- **Evidence required:** either tool output showing the file resolved on the deerflow side under `Paths.acp_workspace_dir(<tid>)`, or a code-quote of the constant location.
- **Pass criterion:** ACP-side path is `/mnt/acp-workspace/...` (unchanged), deerflow-side path read is a real host path under the thread directory.

### S14. App startup without legacy fields produces zero deprecation warnings

- **Category:** cross-process
- **Source:** S9's negative twin.
- **Path:** with a clean `config.yaml` (no `sandbox.use`), restart and grep boot logs.
- **Evidence required:** grep showing zero hits.
- **Pass criterion:** no WARNING line mentioning `sandbox.use`.

### S15. Old chat threads with rendered legacy artifact URLs still load in the UI

- **Category:** ui-render
- **Source:** Contract artifact-route back-compat.
- **Path:** open an existing pre-refactor thread (if one is available in the dev DB) that has rendered messages containing `/api/threads/<tid>/artifacts/mnt/user-data/...` URLs. Click each to verify.
- **Evidence required:** screenshot of the artifact rendering, or "no pre-refactor thread available — covered by S5 curl back-compat instead".
- **Pass criterion:** every legacy link resolves to a 200 and renders.

---

## Adversarial (P2)

### S16. `present_file_tool` rejects a path outside `outputs_path`

- **Category:** destructive (input validation)
- **Source:** Contract `present_file_tool` whitelist via `thread_data.outputs_path`.
- **Path:** in a fresh thread: `Try to call present_file with the absolute path "/etc/hostname".`
- **Evidence required:** assistant's reply containing the tool error.
- **Pass criterion:** tool refuses with an error mentioning "outside outputs" (or equivalent); no file leaked to the UI; no traceback.

### S17. Path-traversal attempt on artifact route returns 403

- **Category:** destructive
- **Source:** Contract artifact-route resolves under `user_data` only.
- **Path:**
  ```
  curl -i "http://localhost:8001/api/threads/<tid>/artifacts/uploads/../../../../etc/passwd"
  ```
- **Evidence required:** response status line.
- **Pass criterion:** 403 (or 404), never 200, never a passwd file body.

### S18. Boot succeeds with malformed legacy `sandbox.mounts` block

- **Category:** cross-process (hardening)
- **Source:** Contract `extra="allow"` keeps unknown fields working.
- **Path:** add `sandbox.mounts: [{"src": "/foo", "dst": "/bar"}]` to `config.yaml`, restart.
- **Evidence required:** boot log + `/health` 200.
- **Pass criterion:** boot succeeds; field is silently ignored; gateway healthy.

---

## Already covered by automation (🔍 not for manual run)

- 🔍 `Sandbox.execute_command(cwd=...)` honoured — `backend/tests/test_local_sandbox_cwd.py` (added in `80f63e38`).
- 🔍 `bash_tool` defaults cwd to `thread_data.workspace_path` — `backend/tests/test_bash_tool_cwd.py` (`d4798548`).
- 🔍 `bash_tool` no host-bash gate, no bwrap branch — `backend/tests/test_bash_tool_routing.py` (`3f184d63`, `2a7ff733`).
- 🔍 `get_sandbox()` returns singleton; `get_sandbox_provider` no longer importable — `backend/tests/test_get_sandbox_singleton.py` (`9ee4e44e`).
- 🔍 `SandboxMiddleware` not in chain — `backend/tests/test_middleware_chain_no_sandbox.py` (`52135dc0`).
- 🔍 `ThreadState` has no `sandbox` field — `backend/tests/test_thread_state_schema.py` (`6e758efa`).
- 🔍 `apply_prompt_template` substitutes `{workspace,uploads,outputs,skills}_path` — `backend/tests/test_apply_prompt_template_path_vars.py` (`b1c79800`).
- 🔍 Subagent prompts are placeholder-free post-resolve — `backend/tests/test_subagent_prompt_paths.py`, `test_subagent_prompt_security.py` (`77c8ff7b`).
- 🔍 `uploads_middleware` substitutes real `uploads_path` — `backend/tests/test_uploads_middleware_core_logic.py` (`93ccf90b`).
- 🔍 `summarization_middleware` resolves real skills host path — `backend/tests/test_summarization_middleware.py` (`93ccf90b`).
- 🔍 `present_file_tool` accepts host paths under outputs, rejects outside — `backend/tests/test_present_file_tool_core_logic.py` (`73717a61`). (S16 adds an LLM-driven cross-check; the unit test alone covers the rejection path.)
- 🔍 Artifact route accepts both new and legacy shapes — `backend/tests/test_artifacts_router.py` (`cf352df5`). (S5 and S15 still required to verify this on the live gateway.)
- 🔍 Uploads router emits short URL — `backend/tests/test_uploads_router.py` (`b91db157`, `cf352df5`).
- 🔍 `SandboxConfig` shrunk to three fields, legacy fields silently allowed — `backend/tests/test_sandbox_config_compat.py` (`5ff7ef69`, `ed642277`).
- 🔍 Legacy `sandbox.use` warning emitted exactly once — `backend/tests/test_legacy_sandbox_config_warning.py` (`a9b1089c`). (S9 still required: the unit test mocks the hook; live boot verifies the hook is actually wired into startup.)
- 🔍 Lead-agent prompt has no `/mnt/*` literals — `backend/tests/test_lead_agent_prompt.py` (updated in `8db3b437`).
- 🔍 Skills loader no longer reads `container_path` — `backend/tests/test_skills_loader.py` (`87c3ca42`).

---

## Out of scope

- **Multi-worker / production gateway**: S9 assumes single-process dev stack; verifying the deprecation-warning emission across N gunicorn workers is not feasible locally.
- **Pre-refactor thread DB fixture**: S15 may degrade to "covered by S5 curl" if no pre-refactor thread exists in the dev database — note this in the report.
- **AioSandbox runtime regressions**: the module is deleted; we rely on `ImportError` (covered by import-time tests) rather than runtime behaviour, since there is nothing to run.
- **Windows host bash**: the refactor preserves Windows shell-detection in `LocalSandbox`, but smoke is Linux-only.
