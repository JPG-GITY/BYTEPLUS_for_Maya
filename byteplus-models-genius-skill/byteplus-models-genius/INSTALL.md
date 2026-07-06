# Model Genius — Installation Guide

**Model Genius** (`byteplus-models-genius`) is an expert technical assistant for the BytePlus ModelArk platform (Seed 2.0, Seedream, Seedance, VideoPilot, 3D, embeddings, billing & ops). It ships as a standard skill: a `SKILL.md` plus a `references/` folder, and works in both **Claude Code** and **OpenAI Codex** — same package, only the install folder changes.

**Package:** `byteplus-models-genius-skill.tar.gz`
**Contents after extraction:** `byteplus-models-genius/SKILL.md` + `byteplus-models-genius/references/` (7 reference files)

---

## Install in Codex

Codex reads skills from these locations (in priority order):
- **Per user (all projects):** `~/.agents/skills/`
- **Per project (repo):** `.agents/skills/` at the repo root
- Admin `/etc/codex/skills` and built-in system skills

### Option A — All projects (recommended)

```bash
mkdir -p ~/.agents/skills
tar -xzf byteplus-models-genius-skill.tar.gz -C ~/.agents/skills
ls ~/.agents/skills/byteplus-models-genius     # should show: SKILL.md  references/
```

### Option B — Single project

```bash
mkdir -p /path/to/project/.agents/skills
tar -xzf byteplus-models-genius-skill.tar.gz -C /path/to/project/.agents/skills
```

*(You can also just copy the `byteplus-models-genius/` folder — with its `SKILL.md` and `references/` subfolder — into the target `skills/` directory instead of extracting the tar.)*

---

## Install in Claude Code

```bash
mkdir -p ~/.claude/skills
tar -xzf byteplus-models-genius-skill.tar.gz -C ~/.claude/skills
ls ~/.claude/skills/byteplus-models-genius     # should show: SKILL.md  references/
```

---

## Install folder by tool

| Tool | Install folder |
|---|---|
| **Claude Code** | `~/.claude/skills/` (or plugin skills) |
| **Codex** (user) | `~/.agents/skills/` |
| **Codex** (project) | `<repo>/.agents/skills/` |

> Both tools share the **same skill format** (`SKILL.md` with `name`/`description` + `references/` + progressive disclosure), so the **same `.tar.gz`** works in both — only the destination folder changes.

---

## How to use it

- Type **`/skills`** (or **`$`** in Codex) and select `byteplus-models-genius`, **or**
- Just ask — the assistant triggers it **automatically** when your question matches the description, e.g. *"Hi Model Genius…"* or any question about ModelArk, Seedance, Seedream, Seed 2.0, VideoPilot, or the `ark.ap-southeast.bytepluses.com` APIs.

---

## Verify the install

```bash
# Codex (user-level)
cat ~/.agents/skills/byteplus-models-genius/SKILL.md | head -4
ls  ~/.agents/skills/byteplus-models-genius/references

# Claude Code
cat ~/.claude/skills/byteplus-models-genius/SKILL.md | head -4
ls  ~/.claude/skills/byteplus-models-genius/references
```

You should see the YAML frontmatter (`name:` / `description:`) and 7 files under `references/`. If `references/` is missing, the skill was installed without its bundled research — re-extract the full folder so the reference files travel alongside `SKILL.md`.
