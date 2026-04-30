# Smoke checklist — agent reconfigure flow

Date drafted: 2026-04-30
Plan: docs/superpowers/plans/2026-04-30-agent-reconfigure.md
Diff window: 57b20abf..HEAD
Mode: whole-plan

## Spec gaps (smoke may be incomplete)

- The plan was authored without a referenced spec, so no `## Contract surface` section was available as input. This checklist was derived using the **diff-only fallback heuristic** described in `generating-smoke-checklists`. Coverage of cross-component effects (e.g. interactions with the existing lead_agent / agents API / message rendering) may be incomplete; reviewers should sanity-check by browsing the changed files alongside the smoke run.

## Required (P0)

### S1. Reconfigure entry button is visible and routes correctly

- **Category:** ui-render
- **Source:** fallback rule for `frontend/src/components/workspace/agents/agent-card.tsx` (component change → browser smoke)
- **Path:**
  1. Visit `http://localhost:3000/workspace/agents`
  2. Hover over any existing agent card (e.g. `code-writer`)
- **Evidence required:** screenshot showing the card with a settings (gear) icon button between the chat button and trash button. Then click the settings button and capture URL bar.
- **Pass criterion:** settings icon is visible alongside Chat/Trash; clicking it navigates to `/workspace/agents/<name>/configure` (URL bar shows the route).

### S2. Configure page loads existing agent into bootstrap chat

- **Category:** composition
- **Source:** fallback rule for `frontend/src/app/workspace/agents/[agent_name]/configure/page.tsx` (new page → browser smoke); also exercises `BootstrapChatShell` mounted in `mode="reconfigure"`.
- **Path:**
  1. From S1, you are on `/workspace/agents/code-writer/configure`.
  2. Wait for page to settle (≤2s).
- **Evidence required:** screenshot of full page showing:
  - header reading something like `重新引导：code-writer` (or `Reconfigure: code-writer`)
  - chat panel with at least one bootstrap seed message visible (the seed contains the agent's name and a sentence about "继续完善" / "keep refining")
  - Save dropdown visible top-right
  - prompt input visible at bottom
- **Pass criterion:** all four UI elements present; no error toast; no console error in DevTools.

### S3. Reconfigure save path overwrites SOUL.md and merges config.yaml

- **Category:** cross-process + destructive
- **Source:** fallback rule for `backend/.../setup_agent_tool.py` (public route reachable via tool call) — and the only meaningful e2e of the merge logic. Unit tests (🔍 below) cover the file-IO logic but not the LLM tool-invocation wire.
- **Pre-condition (operator must seed):**
  ```bash
  AGENT=$(ls backend/.deer-flow/agents | head -1)
  # Append model and tool_groups so the merge has something non-trivial to preserve
  python3 -c "
  import yaml, pathlib
  p = pathlib.Path('backend/.deer-flow/agents/$AGENT/config.yaml')
  d = yaml.safe_load(p.read_text()) or {}
  d['model'] = 'doubao-seed-2.0'
  d['tool_groups'] = ['coding']
  p.write_text(yaml.dump(d, allow_unicode=True))
  cat backend/.deer-flow/agents/$AGENT/config.yaml
  "
  cat backend/.deer-flow/agents/$AGENT/SOUL.md | head -3
  ```
- **Path:**
  1. Visit `/workspace/agents/<the AGENT>/configure`.
  2. In the chat, send a short instruction such as "在 SOUL 里加一句:'回复要简明扼要,优先列点'。" or any visible behavioural change request.
  3. Wait for the LLM to reply, then open the top-right `⋯` dropdown and click Save (`保存智能体`).
  4. Wait for completion card to appear (`智能体已更新！` / `Agent updated`).
- **Evidence required:** paste the post-run state of the agent dir:
  ```bash
  cat backend/.deer-flow/agents/<AGENT>/config.yaml
  head -10 backend/.deer-flow/agents/<AGENT>/SOUL.md
  ```
  Plus screenshot of the completion card with hint paragraph visible (reconfigure-only).
- **Pass criterion:**
  - `config.yaml` still contains `model: doubao-seed-2.0` AND `tool_groups: [coding]` (operator-curated fields preserved)
  - `config.yaml` `name` matches the agent name
  - `config.yaml` `description` may have been updated (LLM's choice; OK either way)
  - `SOUL.md` content has visibly changed and reflects the new instruction
  - completion card shows the reconfigure-mode hint paragraph (not just the title)

### S4. Existing create flow still works (refactor regression check)

- **Category:** composition
- **Source:** fallback rule for `frontend/src/app/workspace/agents/new/page.tsx` (modified) — the refactor in T3 dropped ~240 lines of state/effects.
- **Path:**
  1. Visit `/workspace/agents`.
  2. Click `+ New Agent`.
  3. Step 1: enter a unique name (e.g. `smoke-create-<timestamp>`), click Continue.
  4. Step 2: chat panel appears, seed message auto-arrives.
  5. Send one short instruction.
  6. Click Save in the top-right dropdown.
  7. Wait for completion card.
- **Evidence required:**
  - URL bar at each step (name → chat → completion)
  - screenshot of the completion card (it should NOT have the reconfigure hint paragraph — only `agentCreated` title + Start Chatting / Back to Gallery buttons)
  - `ls backend/.deer-flow/agents/smoke-create-<ts>/` showing both `config.yaml` and `SOUL.md`
- **Pass criterion:**
  - Step 1 successfully creates the placeholder dir
  - Step 2 chat seeds one message (not zero, not duplicates)
  - Save completes; completion card appears with create-mode copy (no reconfigure hint paragraph)
  - Files exist on disk

## Recommended (P1)

### S5. Configure route handles missing agent (404 fallback)

- **Category:** ui-render + destructive (delete-while-open)
- **Source:** fallback rule + plan task 4 explicitly specifies the missing-agent state.
- **Path:**
  1. Visit `/workspace/agents/this-name-does-not-exist/configure` directly.
- **Evidence required:** screenshot showing `找不到该智能体。可能它已被删除。` (or English equivalent) plus a `← 返回 Gallery` button.
- **Pass criterion:** no console errors, no infinite loading spinner, the back button routes to `/workspace/agents`.

### S6. Reconfigure flow can be cancelled by closing the page mid-chat

- **Category:** destructive
- **Source:** fallback rule — closing mid-flow is a state-management edge.
- **Path:**
  1. Start S3 above (`/workspace/agents/<AGENT>/configure` with model/tool_groups pre-seeded).
  2. Send one chat message; while LLM is still streaming, navigate away via sidebar to `/workspace/chats`.
  3. Re-open `/workspace/agents/<AGENT>/configure`.
- **Evidence required:**
  - `cat backend/.deer-flow/agents/<AGENT>/config.yaml` — should be unchanged from pre-condition (no Save was ever clicked)
  - screenshot of the re-opened configure page: it should mount **a fresh thread** (no leftover messages from the abandoned attempt)
- **Pass criterion:** `config.yaml` untouched (model/tool_groups still present, SOUL.md unchanged); fresh thread on re-entry.

### S7. Save-hint Alert appears once across both create and reconfigure

- **Category:** time-window (state stored across visits)
- **Source:** the shell shares `SAVE_HINT_STORAGE_KEY = "deerflow.agent-create.save-hint-seen"` across both modes. Carry-over behaviour from the original.
- **Path:**
  1. Open DevTools → Application → Local Storage → `localhost:3000`.
  2. **If the key exists, delete it.** (Smoke must start fresh.)
  3. Visit a configure page → observe Alert at top of chat panel.
  4. Refresh page or go elsewhere → return → Alert should NOT reappear.
  5. Visit `/workspace/agents/new`, complete name step → Alert should NOT reappear (already seen in step 3).
- **Evidence required:** screenshots of step 3 (Alert visible) and step 5 (Alert absent), plus localStorage key value `1`.
- **Pass criterion:** Alert appears exactly once; key persists.

## Adversarial (P2)

### S8. Reconfigure during a corrupt config.yaml falls back gracefully

- **Category:** destructive
- **Source:** code review found the merge falls back to `existing = {}` on parse error with a warning log. No automated test exercises this branch.
- **Pre-condition:**
  ```bash
  AGENT=smoke-corrupt-$RANDOM
  mkdir -p backend/.deer-flow/agents/$AGENT
  echo "this is not yaml: { unclosed" > backend/.deer-flow/agents/$AGENT/config.yaml
  echo "old soul" > backend/.deer-flow/agents/$AGENT/SOUL.md
  ```
  Then directly visit `/workspace/agents/$AGENT/configure`.
- **Path:** complete the reconfigure save flow as in S3.
- **Evidence required:**
  - `tail -50 logs/gateway.log` showing the warning line `failed to parse existing ...`
  - post-run `cat backend/.deer-flow/agents/$AGENT/config.yaml` — should be a fresh-write (no recovered fields)
  - SOUL.md updated
- **Pass criterion:** save succeeds; the existing corrupt YAML is silently treated as empty (the fallback logged but no crash).

### S9. Direct configure URL with an agent that has a name containing whitespace or odd chars

- **Category:** ui-render
- **Source:** adversarial — `useParams` returns whatever's in the URL; the page passes it straight to `getAgent`. If an agent name contained `/` or url-unsafe chars, behaviour is unspecified.
- **Path:** visit `/workspace/agents/my%20agent/configure` (URL-encoded space).
- **Evidence required:** screenshot of resulting state (likely "agent not found" because no such agent exists). No crash, no infinite spinner.
- **Pass criterion:** graceful 404 fallback, same as S5.

## Already covered by automation (🔍 not for manual run)

- 🔍 `setup_agent` merges with existing config.yaml — covered by `backend/tests/test_setup_agent_tool.py::test_setup_agent_preserves_existing_model_and_tool_groups`. Unit test stubs filesystem paths and runtime; **end-to-end is S3**.
- 🔍 `setup_agent` produces minimal config when none exists — covered by `backend/tests/test_setup_agent_tool.py::test_setup_agent_creates_minimal_config_when_no_existing_file`.
- 🔍 `BootstrapChatShell` seeds conversation once on mount — covered by `frontend/tests/unit/components/workspace/agents/bootstrap-chat-shell.test.tsx` (3 tests). Shell internals stubbed; **real-stack mount is S2 + S4**.
- 🔍 ConfigurePage missing-agent fallback (logic only) — covered by `frontend/tests/unit/app/workspace/agents/configure-page.test.tsx::shows not-found state when agent missing`. Real network 404 is **S5**.
- 🔍 ConfigurePage mounts shell with reconfigure props — covered by `frontend/tests/unit/app/workspace/agents/configure-page.test.tsx::mounts shell with reconfigure props when agent exists`. Stubs out the shell; real composition is **S2**.
- 🔍 AgentCard renders reconfigure button + click routes to /configure — covered by `frontend/tests/unit/components/workspace/agents/agent-card.test.tsx` (2 tests). Real visual integration is **S1**.

## Out of scope

- **Multi-worker gateway race**: `setup_agent` writes config.yaml from one process; if another worker reads simultaneously, behaviour is process-local. Not addressed by this plan.
- **Concurrent reconfigure of the same agent** (two browser tabs both saving): no locking. Last write wins. Acceptable for current single-operator usage.
- **Persistence of in-progress reconfigure conversation**: each `/configure` visit creates a fresh thread (carried-over create-flow behaviour). If we ever want resume, that's a separate plan.
- **UX of the Save dropdown** in reconfigure mode: the menu copy was carried verbatim from create mode (`保存智能体` / `Save agent`). Acceptable; not tested separately.
