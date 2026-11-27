# fun development guide

`fun` is a Python-based Linux terminal screensaver engine with 41 scenes, a GTK4
settings GUI, kitty graphics rendering, and automatic idle detection.
The launcher needs Bash and Python 3.11+. The GUI uses system Python with
PyGObject and GTK4.

## Repository layout

- Root launchers `fun`, `fun-config`, and `fun-idle` work from a complete checkout.
  `extras.py` dispatches Python scenes and their self-tests.
- `fun_app/` contains the active registry and implementations in `scenes/`,
  terminal playback in `renderers/`, GTK settings in `gui/`, idle detection
  in `idle/`, and shared settings and paths.
- `installer/` contains dependency checks, the install manifest, file ownership
  logic, and compatibility shims. `install.sh` and `uninstall.sh` are at the root.
- `tests/` contains the regression suite and GUI smoke test. `tools/rendering/`
  contains renderer diagnostics. `scripts/` contains maintainer checks.
- `assets/` contains gallery and motion assets. `docs/` covers idle inhibition,
  release checks, and GitHub workflows. CI runs from `.github/workflows/verify.yml`.

## Commands

Run checkout commands from the repository root.

- Launch rotation with `./fun`, play one scene with `./fun --scene koi`, or list
  active scenes with `./fun --list`.
- Open settings in a graphical session with `./fun-config` or installed `fun-config`.
- In the graphical session with the installed login watcher running, use
  `fun-idle --diagnose` to check the backend and blockers. Run `fun-idle --test`,
  leave input idle for 10 seconds, then move the mouse to verify dismissal.
  Use `fun-idle --status` to confirm the normal delay has returned.
- With explicit authorization, run `./install.sh` as the desktop user.
- Run regression tests with `/usr/bin/python3 -m unittest discover -s tests -p 'test_*.py'`.
- Run headless scene checks with `./fun --selftest`. CI also runs
  `/usr/bin/python3 -I extras.py --selftest`.

## Compatibility and safety

- Preserve all 41 scenes, original artwork, scene identifiers and aliases.
  Follow approved creative specifications. Keep visual quality and resource
  usage in view, and keep NumPy and other heavy dependencies optional.
- Preserve the 10-minute default rotation, saved settings compatibility,
  public entry points, terminal cleanup, and X11 and Wayland support.
  Keep kitty graphics and the Unicode half-block fallback working.
- Preserve installation paths under `/usr/local/bin` and `/usr/local/lib/fun`
  and the per-user XDG autostart and applications paths.
- Never bypass legitimate KDE inhibitors, silently change power or lock settings,
  delete unverified project files, or weaken installer or uninstaller ownership
  checks, including legacy adoption and manifest validation.

## Workflow and Git identity

- Inspect actual files and use targeted searches and edits. Keep a pre-edit
  backup outside the checkout. Consult `REFINE.md`, `GFX.md`, or
  milestone notes when available and relevant. Keep scene edits with one agent.
- Reuse existing verification tools, run relevant tests, batch visual previews,
  and self-review the diff. Use the release checklist for release verification.
- Stop at the requested scope or approved milestone. Obtain explicit authorization
  before committing, pushing, merging, tagging, releasing, or modifying system
  installations, including direct edits under `/usr/local`.
- Use repository-local Git configuration for all agent-created commits and tags.
  The author, committer, and annotated tagger must be
  `Slavro-1 <Slavro-1@users.noreply.github.com>`. Before committing or tagging,
  verify `git var GIT_AUTHOR_IDENT` and `git var GIT_COMMITTER_IDENT`.
  Never add AI attribution or `Co-authored-by` trailers or rewrite history to
  change attribution.
