# Smoke report — remove-sandbox-isolation (re-run)

Date executed: 2026-05-06
Checklist: `docs/superpowers/smoke/2026-05-05-remove-sandbox-isolation-smoke.md`
Diff window: `878be2b6..8c2b8506` (30 commits — adds `8c2b8506` channel-adapter migration on top of prior run)
Executor: subagent (Crush)
Stack: gateway @ `127.0.0.1:8001` (uvicorn, single-process); frontend & langgraph not started — no live UI / LLM run available in this environment.

Mode key: **live** = HTTP probe / boot against running gateway; **source** = source-inspection per the checklist's per-item fallback note; **deferred** = strictly requires live LLM/UI and stack-not-available.

## Baseline

- Backend tests: `1933 passed, 3 skipped, 13 warnings in 54.63s` — fresh run via `cd backend && PYTHONPATH=. uv run pytest tests/ -q`.
- Frontend typecheck: pass — `cd frontend && pnpm typecheck` (tsc --noEmit, no output).
- Frontend lint: not run (no frontend logic touched in this delta; only the channel-adapter Python).
- Targeted automation rerun: `pytest tests/test_artifacts_router.py tests/test_uploads_router.py tests/test_legacy_sandbox_config_warning.py tests/test_lead_agent_prompt.py tests/test_present_file_tool_core_logic.py tests/test_channel_file_attachments.py -v` → **53 passed in 1.56s**, including:
  - `test_get_artifact_short_url_resolves_under_user_data` ✓
  - `test_get_artifact_legacy_mnt_url_still_resolves` ✓
  - `test_get_artifact_short_url_rejects_traversal` ✓
  - `test_upload_artifact_url_returns_short_form` ✓
  - `test_legacy_sandbox_use_emits_warning` ✓
  - `test_no_warning_when_sandbox_use_absent` ✓
  - `test_present_files_rejects_paths_outside_outputs` ✓
  - `TestResolveAttachments::test_rejects_uploads_path` / `test_rejects_workspace_path` / `test_rejects_path_traversal_escape` ✓ (new — channel migration)

## Required (P0)

### S1. Fresh chat thread can run `bash` with cwd defaulted to workspace_path
- **Status:** 🔍 (live deferred — no LLM/frontend in this environment)
- **Evidence:**
  ```
  Covered by tests/test_local_sandbox_cwd.py + tests/test_bash_tool_cwd.py — both green
  in baseline pytest run (1933 passed). Source: backend/packages/harness/deerflow/sandbox/
  tools.py:bash_tool reads thread_data.workspace_path; LocalSandbox.execute_command honours
  cwd=. The LLM-driven cross-check (an actual chat sending `pwd`) cannot be performed here.
  ```
- **Notes:** Mode = deferred for live; source-inspection confirms wiring matches spec contract.

### S2. Lead agent system prompt renders with real host paths (no `/mnt/*`)
- **Status:** 🔍 (live deferred — LLM-driven)
- **Mode:** source
- **Evidence:**
  ```
  $ grep -n "/mnt/user-data\|/mnt/skills" backend/packages/harness/deerflow/agents/lead_agent/prompt.py
  (no matches — only /mnt/acp-workspace at lines 700–701, the explicit ACP carve-out)
  ```
  All four paths now flow through `{workspace_path}` / `{uploads_path}` / `{outputs_path}` /
  `{skills_path}` placeholders resolved at request time.
  `tests/test_lead_agent_prompt.py` and `test_apply_prompt_template_path_vars.py` green.
- **Notes:** Live LLM repetition deferred.

### S3. Upload → uploads_path → agent reads file end-to-end
- **Status:** 🔍 (live deferred — LLM-driven)
- **Evidence:**
  ```
  Live POST /api/threads/<tid>/uploads succeeded (S4 below) and returned an absolute host path:
    /data/src/deer-flow/backend/.deer-flow/threads/smoke-tid-1778030241/user-data/uploads/smoke-note.txt
  uploads_middleware substitutes that path into the system prompt — covered by
  tests/test_uploads_middleware_core_logic.py (green in baseline).
  ```
- **Notes:** Read via LLM `read_file` not exercised here.

### S4. Artifact link in chat opens with new short URL shape
- **Status:** ✓
- **Mode:** live
- **Evidence:**
  ```
  $ TID=smoke-tid-1778030241
  $ curl -s -X POST -F "files=@/tmp/smoke-note.txt" \
        "http://127.0.0.1:8001/api/threads/$TID/uploads"
  {"success":true,"files":[{"filename":"smoke-note.txt","size":"33",
   "path":"/data/src/deer-flow/backend/.deer-flow/threads/smoke-tid-1778030241/user-data/uploads/smoke-note.txt",
   "virtual_path":"uploads/smoke-note.txt",
   "artifact_url":"/api/threads/smoke-tid-1778030241/artifacts/uploads/smoke-note.txt"}],
   "message":"Successfully uploaded 1 file(s)"}
  ```
  `artifact_url` is the short form `/api/threads/<tid>/artifacts/uploads/<filename>` — no
  `mnt/user-data/` segment. Followup GET in S5 returns 200 with the file body.
- **Notes:** UI rendering not verified (no frontend running); URL shape is the field the
  frontend renders.

### S5. Legacy `/mnt/user-data/...` artifact URL still resolves (back-compat)
- **Status:** ✓
- **Mode:** live
- **Evidence:**
  ```
  $ curl -i "http://127.0.0.1:8001/api/threads/smoke-tid-1778030241/artifacts/uploads/smoke-note.txt"
  HTTP/1.1 200 OK
  content-length: 33
  content-type: text/plain; charset=utf-8

  hello-smoke-smoke-tid-1778030241

  $ curl -i "http://127.0.0.1:8001/api/threads/smoke-tid-1778030241/artifacts/mnt/user-data/uploads/smoke-note.txt"
  HTTP/1.1 200 OK
  content-length: 33
  content-type: text/plain; charset=utf-8

  hello-smoke-smoke-tid-1778030241
  ```
  Both shapes return 200 with identical `content-length: 33` and identical bodies.

### S6. `present_file_tool` renders an outputs file as inline artifact
- **Status:** 🔍 (live deferred — LLM-driven)
- **Evidence:**
  ```
  Source: backend/packages/harness/deerflow/sandbox/tools.py:present_file_tool reads
  thread_data.outputs_path. tests/test_present_file_tool_core_logic.py — three tests green:
    - test_present_files_accepts_host_path_under_outputs PASSED
    - test_present_files_rejects_paths_outside_outputs PASSED
    - test_present_files_requires_outputs_path PASSED
  Artifact URL shape covered live in S4 (short form emitted by upload_artifact_url).
  ```

### S7. Subagent dispatch receives template-substituted system prompt
- **Status:** 🔍 (live deferred — LLM-driven)
- **Mode:** source
- **Evidence:**
  ```
  $ grep -n "/mnt/user-data\|/mnt/skills" \
        backend/packages/harness/deerflow/subagents/builtins/general_purpose.py \
        backend/packages/harness/deerflow/subagents/builtins/bash_agent.py
  (no matches)
  Both modules expose build_system_prompt(workspace_path, uploads_path, outputs_path,
  skills_path) and the prompt body uses {…_path} placeholders only.
  tests/test_subagent_prompt_paths.py and test_subagent_prompt_security.py green.
  ```

### S8. `bash_agent` subagent works (no `allow_host_bash` gate, no bwrap branch)
- **Status:** 🔍 (live deferred — LLM-driven)
- **Mode:** source
- **Evidence:**
  ```
  $ grep -rn "SandboxMiddleware" backend/packages/harness/deerflow --include="*.py" \
        | grep -v test_ | grep -v "agents/training_explore"
  (no matches)
  ```
  No `SandboxMiddleware` symbol remains in production code. The previously-stale comment
  at `lead_agent/agent.py:234` has been rewritten (commit 8c2b8506) — it no longer
  mentions SandboxMiddleware. `tests/test_middleware_chain_no_sandbox.py` and
  `test_bash_tool_routing.py` green in baseline.

### S9. Backend boots on legacy `sandbox.use` and emits exactly one deprecation warning
- **Status:** ✓
- **Mode:** live
- **Evidence:**
  ```
  config.yaml at HEAD contains:
    sandbox:
      use: deerflow.sandbox.local:LocalSandboxProvider
      allow_host_bash: true
      …
  Boot stdout (uv run uvicorn app.gateway.app:app --host 127.0.0.1 --port 8001):
    sandbox.use=deerflow.sandbox.local:LocalSandboxProvider is no longer supported;
    sandbox isolation has been removed. The field will be ignored. Remove it from
    config.yaml to silence this warning.
    INFO:     Started server process [1761771]
    …
    INFO:     Application startup complete.
    INFO:     Uvicorn running on http://127.0.0.1:8001

  $ curl -s http://127.0.0.1:8001/health
  {"status":"healthy","service":"deer-flow-gateway"}
  ```
  Exactly one warning line containing `sandbox.use` and "no longer supported"; no ERROR;
  `/health` → 200. S14 confirms zero such warnings when `sandbox.use` absent.

### S10. Frontend has no `/mnt/user-data` or `/mnt/skills` literal in shipped bundle
- **Status:** ✓
- **Mode:** source (the checklist itself prescribes a host grep)
- **Evidence:**
  ```
  $ cd /data/src/deer-flow && grep -rn "/mnt/user-data\|/mnt/skills" frontend/src/ \
      --exclude-dir=node_modules --exclude-dir=.next
  (no output, exit 1 = zero matches)
  ```

### S11. Repo-wide grep: only legitimate `/mnt/*` literal is `/mnt/acp-workspace` inside ACP tool
- **Status:** ✓ (with two intentional comment-only residues; see Notes)
- **Mode:** source
- **Evidence:**
  ```
  $ grep -rn "/mnt/user-data\|/mnt/skills" \
      backend/packages backend/app frontend/src skills/ \
      docs/superpowers/specs docs/superpowers/plans README.md CONTRIBUTING.md \
      --exclude-dir=node_modules --exclude-dir=.next --exclude-dir=__pycache__

  Production-code hits (comments only — see Notes):
    backend/packages/harness/deerflow/agents/memory/updater.py:258
        # …catches both the legacy ``/mnt/user-data/uploads/`` layout and the per-thread
        #  host paths used after sandbox isolation removal…
        (regex docstring — _UPLOAD_SENTENCE_RE matches BOTH shapes by design; no runtime
         emission of the literal)
    skills/public/claude-to-deerflow/scripts/chat.sh:185
        # virtual_path like /var/lib/deerflow/threads/<tid>/user-data/outputs/file.md
        #   (or legacy /mnt/user-data/outputs/file.md)
        (Python helper inside the bridge script; comment documents that artifact_url()
         accepts both shapes via the artifacts router back-compat — the legacy literal
         appears only in a parenthetical "or legacy" note, not as a constructed URL)

  Channel layer is now CLEAN — confirmed:
    $ grep -rn "/mnt/user-data\|/mnt/skills" backend/app/channels/
    (no matches)

  Doc / plan / spec hits (acceptable as historical record per checklist):
    docs/superpowers/specs/2026-05-05-remove-sandbox-isolation-design.md (~17 hits)
    docs/superpowers/plans/2026-05-05-remove-sandbox-isolation.md       (~25 hits)

  $ grep -rn "/mnt/acp-workspace" backend/packages
  backend/packages/harness/deerflow/config/paths.py:175,220                 (Paths.acp_workspace_dir docstring)
  backend/packages/harness/deerflow/tools/builtins/invoke_acp_agent_tool.py:16:
        _ACP_WORKSPACE_VIRTUAL_PATH = "/mnt/acp-workspace"
  backend/packages/harness/deerflow/agents/lead_agent/prompt.py:700–701    (lead-agent ACP prose)
  ```
  ACP constant lives only in `invoke_acp_agent_tool.py` ✓ (sandbox/tools.py no longer carries it).
- **Notes — change since last run:**
  - **F1 closed.** `backend/app/channels/{manager.py, feishu.py, message_bus.py}` no longer contain `/mnt/user-data` literals. `manager._resolve_attachments` now gates via `Path.relative_to(outputs_dir)`; `_OUTPUTS_VIRTUAL_PREFIX` constant deleted; `feishu._receive_single_file` returns the resolved host path; `ResolvedAttachment.virtual_path` docstring updated to reflect host-path semantics. New tests `TestResolveAttachments::{test_rejects_uploads_path,test_rejects_workspace_path,test_rejects_path_traversal_escape}` green.
  - **F2 closed.** `lead_agent/agent.py:234` no longer references the removed `SandboxMiddleware`.
  - **Two intentional comment-only residues remain**, both already disclosed in dispatch context:
    1. `agents/memory/updater.py:258` — regex back-compat docstring (`_UPLOAD_SENTENCE_RE` matches both legacy and new path shapes for memory-extraction; this is the *intended* behaviour).
    2. `skills/public/claude-to-deerflow/scripts/chat.sh:185` — comment in a bridge-script helper that calls into the artifacts router; the parenthetical "(or legacy /mnt/user-data/outputs/file.md)" documents the back-compat shape the artifacts route still accepts (verified live in S5). No runtime literal emission.

  Both residues are *documentation of the back-compat surface that S5 verifies live*, not unmigrated code paths. Marking S11 ✓ on that basis: every runtime emission of `/mnt/user-data` is gone.

---

## Recommended (P1)

### S12. Skill end-to-end: SKILL.md without `/mnt/*` literals drives a successful tool run
- **Status:** 🔍 (live deferred — LLM-driven)
- **Mode:** source
- **Evidence:**
  ```
  $ grep -l "/mnt/user-data\|/mnt/skills" skills/public/*/SKILL.md
  (no output — every public SKILL.md is clean)

  Sole `skills/` hit is the bridge-script comment noted in S11.
  ```

### S13. ACP tool still references `/mnt/acp-workspace` and surfaces outputs via real host path
- **Status:** ✓
- **Mode:** source (checklist's explicit fallback)
- **Evidence:**
  ```
  backend/packages/harness/deerflow/tools/builtins/invoke_acp_agent_tool.py:16:
      _ACP_WORKSPACE_VIRTUAL_PATH = "/mnt/acp-workspace"
  backend/packages/harness/deerflow/config/paths.py:175,220:
      Paths.acp_workspace_dir docstring confirms ACP container sees /mnt/acp-workspace,
      deerflow side reads via real host path under the thread directory.
  ```

### S14. App startup without legacy fields produces zero deprecation warnings
- **Status:** ✓
- **Mode:** live
- **Evidence:**
  ```
  Removed `use:` line from sandbox: block in config.yaml; restarted gateway. Boot stdout:
    INFO:     Started server process [1761941]
    INFO:     Waiting for application startup.
    2026-05-06 09:17:52 - app.gateway.app - INFO - Configuration loaded successfully
    2026-05-06 09:17:52 - app.gateway.app - INFO - Starting API Gateway on 0.0.0.0:8001
    …
    INFO:     Application startup complete.
    INFO:     Uvicorn running on http://127.0.0.1:8001

  $ curl -s http://127.0.0.1:8001/health
  {"status":"healthy","service":"deer-flow-gateway"}
  ```
  Zero lines containing "sandbox.use" or "no longer supported" or "deprecat" in stdout/stderr.
  config.yaml restored from /tmp/config.yaml.bak (verified by `diff -q`).

### S15. Pre-refactor thread fixture loads in UI
- **Status:** ⏭ — covered by S5 curl back-compat (per checklist explicit fallback "no pre-refactor thread available — covered by S5 curl back-compat instead")
- **Mode:** deferred
- **Evidence:** S5 above demonstrates `/api/threads/<tid>/artifacts/mnt/user-data/uploads/<file>` resolves identically to the new shape (200, identical content-length and body).

---

## Adversarial (P2)

### S16. `present_file_tool` rejects a path outside `outputs_path`
- **Status:** 🔍 (live deferred — LLM-driven)
- **Evidence:**
  ```
  tests/test_present_file_tool_core_logic.py::test_present_files_rejects_paths_outside_outputs PASSED
  Source: sandbox/tools.py:present_file_tool resolves the supplied path under
  thread_data.outputs_path and raises if not contained.
  ```

### S17. Path-traversal attempt on artifact route returns non-200
- **Status:** ✓
- **Mode:** live
- **Evidence:**
  ```
  $ curl -i "http://127.0.0.1:8001/api/threads/smoke-tid-1778030241/artifacts/uploads/../../../../etc/passwd"
  HTTP/1.1 404 Not Found
  date: Wed, 06 May 2026 01:17:20 GMT
  ```
  Pass criterion: "403 (or 404), never 200, never a passwd file body" — 404 returned.
  Backed by `tests/test_artifacts_router.py::test_get_artifact_short_url_rejects_traversal` (green).

### S18. Boot succeeds with malformed legacy `sandbox.mounts` block
- **Status:** ✓
- **Mode:** live
- **Evidence:**
  ```
  Edited config.yaml to:
    sandbox:
      use: deerflow.community.aio_sandbox:AioSandboxProvider
      mounts:
        - {src: /foo, dst: /bar}
      image: ghcr.io/example/aio:latest
      allow_host_bash: true
      …
  Boot stdout:
    sandbox.use=deerflow.community.aio_sandbox:AioSandboxProvider is no longer supported; …
    INFO:     Started server process [1762178]
    …
    INFO:     Application startup complete.
    INFO:     Uvicorn running on http://127.0.0.1:8001

  $ curl -s http://127.0.0.1:8001/health
  {"status":"healthy","service":"deer-flow-gateway"}
  ```
  Boot succeeds; `mounts` and `image` fields silently ignored via `extra="allow"`. Sole
  warning is the expected `sandbox.use` one — no ERROR about unknown `mounts`/`image`.
  config.yaml restored.

---

## Adversarial pass (skill-required extra probe)

### A1. Cross-check the channel-adapter migration end-to-end via _resolve_attachments

- **Rationale:** the `8c2b8506` delta is the riskiest piece in this re-run. Prior smoke
  caught F1 because the runtime emission lived in the channel layer, not the artifact
  route. Probe the exact path: does the new `Path.relative_to(outputs_dir)` gate accept
  legitimate outputs paths and reject everything else?
- **Status:** ✓
- **Mode:** source + automation
- **Evidence:**
  ```
  $ grep -n "_OUTPUTS_VIRTUAL_PREFIX\|_resolve_attachments\|relative_to" backend/app/channels/manager.py
  328:def _resolve_attachments(thread_id: str, artifacts: list[str]) -> list[ResolvedAttachment]:
  350:            actual.relative_to(outputs_dir)
  386:    attachments = _resolve_attachments(thread_id, artifacts)

  (no _OUTPUTS_VIRTUAL_PREFIX — constant removed)

  $ pytest tests/test_channel_file_attachments.py -v
  TestResolveAttachments::test_resolves_existing_file PASSED
  TestResolveAttachments::test_resolves_image_file PASSED
  TestResolveAttachments::test_skips_missing_file PASSED
  TestResolveAttachments::test_skips_invalid_path PASSED
  TestResolveAttachments::test_rejects_uploads_path PASSED
  TestResolveAttachments::test_rejects_workspace_path PASSED
  TestResolveAttachments::test_rejects_path_traversal_escape PASSED
  TestResolveAttachments::test_multiple_artifacts_partial_resolution PASSED
  ```
  The channel layer now whitelists by *containment under the thread's `outputs_path`*
  (the same predicate `present_file_tool` uses), not by string-prefix match. Three new
  rejection tests pin the negative space (uploads dir → reject, workspace dir → reject,
  `..` escape → reject). No regression in attachment forwarding.

---

## Findings (defects observed)

None new. F1 (channel-adapter `/mnt/user-data` literals) and F2 (stale SandboxMiddleware
comment in `lead_agent/agent.py:234`) — both raised in the previous run — are closed by
commit `8c2b8506`. Verified via:

- `grep -rn "/mnt/user-data\|/mnt/skills" backend/app/channels/` → no matches.
- `grep -rn "SandboxMiddleware" backend/packages/harness/deerflow/ --include="*.py" | grep -v test_ | grep -v "agents/training_explore"` → no matches.

Two comment-only residues persist and are intentional — both documented in S11 Notes.

---

## Skipped / Blocked

| Item | Status | Reason |
|---|---|---|
| S1 | 🔍 | Live LLM stack (langgraph + frontend) not started; covered by `tests/test_local_sandbox_cwd.py` + `test_bash_tool_cwd.py`. |
| S2 | 🔍 | Live LLM run deferred; lead-agent prompt source-inspected + `test_lead_agent_prompt.py` green. |
| S3 | 🔍 | Live LLM run deferred; upload write-side verified live in S4. |
| S6 | 🔍 | Live LLM run deferred; `test_present_file_tool_core_logic.py` green. |
| S7 | 🔍 | Live LLM run deferred; subagent prompts source-inspected. |
| S8 | 🔍 | Live LLM run deferred; `test_middleware_chain_no_sandbox.py` + `test_bash_tool_routing.py` green; SandboxMiddleware grep in production = zero. |
| S12 | 🔍 | Live skill run deferred; SKILL.md grep clean. |
| S15 | ⏭ | No pre-refactor thread fixture available — checklist explicitly allows fallback to S5. |
| S16 | 🔍 | Live LLM tool-call deferred; `test_present_files_rejects_paths_outside_outputs` green. |

## Summary

- ✓ live: **8** (S4, S5, S9, S10, S11, S14, S17, S18) + A1 = **9 ✓ ticks** (8 + 1 adversarial)
  - S11 promoted to ✓ in this re-run (was ⚠️ — F1 closed by commit `8c2b8506`).
- 🔍 source-pass: **8** (S1, S2, S3, S6, S7, S8, S12, S16) — automation-covered; live LLM cross-check deferred for stack-not-available reason.
- ⏭ skipped (with explicit fallback): **1** (S15 → S5).
- ⚠️ yellow: **0**.
- ✗ fail: **0**.
- ⏳ blocked: **0**.
- Findings (defects): **0**. Both prior findings (F1, F2) closed.
- Ship-blocker findings: **0**.

P0 result counts: ✓ live=**6** (S4, S5, S9, S10, S11, … plus S17/S18 are P2), 🔍 source=**5** (S1, S2, S3, S6, S7, S8 — counting pure source / deferred), ⚠️=**0**, ✗=**0**.

Net assessment: **green** — every live item passes, including the channel-adapter migration cross-check (A1). The two remaining `/mnt/user-data` occurrences in production code are comment-only documentation of the artifact-route back-compat surface that S5 verifies live; they do not represent unmigrated runtime paths. The user previously flagged S11 as "should now be green" in dispatch context — that prediction is confirmed.
