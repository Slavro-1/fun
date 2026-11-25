# Release verification checklist

The `v0.1.0` tag records the original source release. For future updates, check the active scene inventory with `python3 extras.py --list`; do not maintain a separate scene count here.

- [ ] Confirm the MIT copyright holder and redistribution rights for code and any media included in the release.
- [ ] Run Python compilation, `bash -n` on shell scripts, `fun --selftest`, and the GUI inventory tests.
- [ ] Run focused PTY checks for graphics fallback, resize, and terminal cleanup when rendering code changes.
- [ ] On the intended desktop, manually check kitty graphics, `fun-config`, idle detection, autostart, installation, and uninstall. Automated checks do not establish desktop or cross-distribution compatibility.
- [ ] On each additional distribution, check command availability, the `/usr/local` install layout, GTK4/PyGObject, terminal previews, and an idle backend before listing it as tested.
- [ ] Review the staged files and diff before a new commit. Create a new tag only when a new release is intended.

Generated previews and local development files are excluded from Git. Add screenshots only after checking that they show current scenes and contain no private desktop content.

## v0.1.1 release candidate

Run the commands in `.github/workflows/verify.yml` from the repository root.
The unittest suite includes disposable-prefix upgrades, conflicts, rollback,
settings validation, GUI scene inventory, rotation and idle watcher fixtures.

On Debian KDE Wayland and Pop!_OS KDE, install the reviewed candidate as the
desktop user, inspect any legacy adoption list, then log out and back in.
Check the actual session backend with `fun-idle --diagnose`. Run
`fun-idle --test`, observe a single fullscreen window and dismiss it with input.
Check `fun-idle --status` and repeat at the saved delay. Check preview, resize,
Ctrl+C and locking during manual playback. Confirm that an active application
idle inhibitor holds off automatic activation. Record the distribution, session
and result for each desktop before tagging.

Before committing, verify both Git identities with `git var GIT_AUTHOR_IDENT`
and `git var GIT_COMMITTER_IDENT`. Use the maintainer's GitHub-confirmed
noreply address in repository-local configuration. Historical author metadata
is already public, including the original release tag.

## Maintainer's two-laptop branch gate

Run `sudo ./scripts/final-prepush.sh` in the reviewed checkout on Pop!_OS.
The desktop user must have a matching sudo audit login UID, trusted SSH host
key and passwordless SSH access to Debian. Set repository-local
`fun.verifyHost` to the Debian SSH destination once per checkout. Both
graphical logins must be active and running the installed candidate. The
verifier reads the root-owned installer manifest with a fixed sudo command
on each laptop. Source tests use private exports of the exact commit.

The gate checks the committed files, both installations, actual GTK windows,
renderer rotation, signal cleanup and idle dismissal. Move the pointer on the
specified laptop after its saver appears. An inhibitor, absent observation,
changed setting, stale install or missing mandatory dependency stops the run.
Installation and machine cleanup are separate maintenance operations. A green
run asks for the exact branch and full commit on the controlling terminal
before pushing that commit. Declining leaves the branch local.
