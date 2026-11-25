# FUN Project — Codex Instructions

Project: Python terminal screensavers, extras.py.
Environment: Python 3.12, kitty, Pop!_OS 24.04 with KDE Plasma.

## Rules
- Visual quality and low resource usage are priorities.
- Claude's approved creative specifications are authoritative.
- Do not independently redesign scene concepts.
- Never edit /usr/local or install without approval.
- Preserve the 10-minute launcher rotation.
- Preserve kitty graphics and half-block fallback.
- Preserve CLI, idle watcher, and terminal cleanup.
- No mandatory NumPy or heavy dependencies.
- One agent editing extras.py; no parallel edits.
- Back up files before modifying them.
- Stop after each approved milestone.

## Git identity
- All Codex-created commits and tags in this repository must use Slavro-1 and the verified GitHub noreply address `Slavro-1@users.noreply.github.com`. Use that identity as author and committer for commits and as the tagger for annotated tags.
- Set the Git identity in repository-local configuration only. Before creating a commit or tag, verify `git var GIT_AUTHOR_IDENT` and `git var GIT_COMMITTER_IDENT`.
- Never add Codex, OpenAI, or AI attribution or co-author trailers. Never invent an email address or rewrite existing history to change attribution.

## Token efficiency
- Never dump the entire extras.py file.
- Locate classes with grep; read targeted line ranges.
- Prefer surgical patches over broad rewrites.
- Read reports and reference files only when relevant.
- Avoid repetitive progress commentary.
- Reuse existing scripts and test tools.
- Batch visual previews.
- Never sacrifice necessary testing for token savings.

## Source of truth
Inspect actual project files before assuming features exist.
Use REFINE.md, GFX.md, GFXQ reports, SCENES.md,
and milestone reports when available.
Do not assume this workspace is a Git repository.

## Efficient execution
- Search for symbols before opening large files.
- Read only relevant code ranges.
- Avoid repeated exploration of unchanged files.
- Use focused tests while iterating; full regression at completion.
- Do not spawn subagents unless parallel work clearly saves time.
- Keep progress updates brief; no repeated summaries.
- Stop after the requested scope.
- Never skip necessary verification to save tokens.
