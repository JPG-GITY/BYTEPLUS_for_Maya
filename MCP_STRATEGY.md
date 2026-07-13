# BYTEPLUS for Maya → MCP Strategy (Proposal)

> Decision document. **No implementation** — it frames the what, how, benefits, risks, and effort.

## 1. Executive summary
We add an **MCP layer** on top of the current plugin so external AI assistants
(Claude Desktop, Claude Code, Cursor) can **drive Maya through natural language**,
reusing the **features we already have** (Dream/Seedream, Render/Seedance, Seed 3D,
image description, automation). It is **additive**: the plugin and its menus stay
unchanged; MCP is a second way to trigger the same functions. It is **not** a rewrite.

## 2. What is MCP (context)
**Model Context Protocol**: an open standard that lets an AI assistant call external
"**tools**." We expose Maya + our BytePlus features as tools → the user types
*"generate a 3D horse and add it to the scene"* in Claude, and the AI runs our
function inside Maya.

## 3. Two different goals — don't confuse them
This is the key strategic point:

| Axis | Question it answers | What delivers it |
|---|---|---|
| **AI control** | *Who drives it?* (natural language, agentic) | **MCP** (or the in-app agent) |
| **Portability** | *Which app does it run in?* (Maya / Blender / Houdini) | **A shared core + thin adapters** — **not** MCP |

**MCP does not make us portable to Blender/Houdini.** It does not abstract the DCC
code: the MCP server still has to speak each app's own API — Maya `maya.cmds`,
Blender `bpy`, Houdini `hou`. Creating geometry, importing, rendering, playblast,
querying the scene — all of that is rewritten per app regardless of MCP.

## 4. Architecture (MCP)

```
AI client (Claude / Cursor)  →  MCP server  →  Maya + current plugin
   "generate a 3D horse"        (bridge proc)   (commandPort open)
      natural language          defines tools,   OUR functions run here,
                                forwards to Maya  no rewrite
```

1. **Maya + plugin**: runs with a `commandPort` open (a socket that executes Python inside Maya).
2. **MCP server**: a lightweight process (Python MCP SDK). Defines the tools and **forwards** each call to the commandPort. **Reuses our code.**
3. **AI client**: connects via **one line in its config file**. No new UI: the user types in the AI instead of using the menu.

## 5. Tools we would expose (mapped to what already exists)

| MCP tool | Current function | Note |
|---|---|---|
| `get_scene_info` | (new, read-only) | Safe, no confirmation |
| `generate_image` | Dream / Seedream | Synchronous |
| `generate_video` | Render / Animate / Seedance | **Async** → returns task id + polling |
| `generate_3d` | Seed 3D (text / image) | **Async** → task id |
| `describe_image` / `prompt_doctor` | Seed Chat | Text |
| `run_maya_python` | Seed Assistant | **With confirmation / sandbox** |

## 6. Portability: Maya → Blender → Houdini (the real accelerator)
The plugin has **two layers**:

1. **BytePlus core** — HTTP to Seedream/Seedance/3D/Seed 2.0, prompt engineering,
   polling, cost, moderation/trust rules. **Does NOT depend on Maya.** This is
   ~70–80% of the logic and is **reusable as-is**.
2. **DCC glue** — viewport capture, playblast, render, mesh import, Qt UI.
   **Maya-specific** (`maya.cmds`, PySide-in-Maya).

**What actually speeds up a port is separating (1) from (2).** Extract a standalone
`byteplus_core`; then porting to Blender/Houdini = reuse the core + write a **thin
adapter** (`bpy` / `hou`) per app.

```
                 ┌─ Maya adapter    (maya.cmds)
byteplus_core ───┼─ Blender adapter (bpy)        ← this gives PORTABILITY
(reusable)       └─ Houdini adapter (hou)
      │
      └─ (optional) MCP server on top            ← this gives AI CONTROL
```

MCP's only contribution to portability is **indirect**: a clean MCP design nudges us
toward this separation. But the credit goes to the **shared core**, not to MCP.
Bonus: with a shared core, **one MCP server** can drive whichever app is running,
each via its thin adapter.

## 7. Phased plan (rough effort: S/M/L)

| Phase | What | Effort |
|---|---|---|
| A | **Refactor: extract `byteplus_core`** (DCC-agnostic) from the Maya glue | **M** |
| 0 | commandPort bridge + MCP server skeleton | **S** |
| 1 | Read-only tools + generate image | **M** |
| 2 | Video + 3D with async handling (task id / progress) | **M** |
| 3 | `run_python` with security guardrails | **M** |
| 4 | Packaging + client-ready config (docs) | **S** |
| 5 | *(if multi-DCC is the goal)* Blender / Houdini adapters on the shared core | **M each** |

## 8. Benefits
- Natural-language control from a powerful AI that **chains** our tools with reasoning, files, and other MCP servers.
- **Reuses** the current code → satisfies the MCP strategy without rebuilding the plugin.
- **Interoperable**: any MCP client can use it (not locked to our window).
- Coexists with the current GUI — nothing breaks.
- The **core refactor** unlocks Blender/Houdini regardless of MCP.

## 9. Risks & mitigations
| Risk | Mitigation |
|---|---|
| **Security** — `run_python` = arbitrary code execution from an external AI | Prior confirmation, `undo chunk`, allow-list, run only what's approved |
| **Long jobs** (video/3D take minutes) | Async tools: return a *task id* + poll/progress, never block |
| **Setup friction** (config, port, extra process) | Installer + 1-page doc; open the port when the plugin loads |
| **Double maintenance** (plugin + server + bridge) | Thin server that only forwards; logic stays in the core |
| **No GUI** for artists who want buttons | MCP is additive — the GUI stays |

## 10. What we need
- MCP SDK (Python) for the server.
- Maya `commandPort` (or a small socket inside Maya).
- Define the tools that map to our functions.
- An AI client to consume it (Claude Desktop / Code / Cursor) + its config.

## 11. Recommendation
**Additive, not a rewrite — and be clear about the goal:**
- **If the goal is multi-DCC (Blender/Houdini):** prioritize the **`byteplus_core` +
  adapters** refactor. MCP is secondary.
- **If the goal is AI / agentic control:** do **MCP**.
- **Best path:** do the core separation first → then MCP sits on top almost for free
  **and** serves all three apps. This is the natural evolution of the **Seed Assistant**
  we already have (same "tools" concept, but driven by an **external** AI instead of
  inside Maya).

## 12. Recommended route (concrete)
A GUI-first, single-DCC plugin is what artists actually use — that stays the product.
The one discipline we add: **extract `byteplus_core` as we finish**, so nothing is
thrown away later.

> ⚠️ Reality check: **the GUI does not port.** Maya (PySide + `maya.cmds`), Blender
> (its own panel/operator system, `bpy`) and Houdini each need the UI + glue rebuilt.
> What ports is the **core** — which is exactly why separating it is the whole game.

**Order of work:**
1. **Finish Maya v1 with GUI** (current plan) — while pulling the DCC-agnostic logic
   into `byteplus_core`. Define a clear "v1 done" to avoid endless scope.
2. **Small MCP PoC on Maya** (once the core exists) — cheap, and it demonstrates the
   MCP strategy without stalling the product.
3. **Port to Blender** (largest, free, huge audience) — reuse the core + a new
   adapter/GUI. **Houdini later**, only if there's demand.

**One-liner for the boss:** *"MCP and multi-DCC both ride on a shared core. I'm
building that core while finishing Maya, so both become cheap afterwards — Maya with
GUI now, MCP as a demo, then Blender/Houdini reusing the core."*

This aligns the **product** (buttons artists like), the **MCP strategy**, and **future
multi-DCC** — without doing everything at once.
