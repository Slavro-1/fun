# Release verification checklist

The `v0.1.0` tag records the original source release. For future updates, check the active scene inventory with `python3 extras.py --list`; do not maintain a separate scene count here.

- [ ] Confirm the MIT copyright holder and redistribution rights for code and any media included in the release.
- [ ] Run Python compilation, `bash -n` on shell scripts, `fun --selftest`, and the GUI inventory tests.
- [ ] Run focused PTY checks for graphics fallback, resize, and terminal cleanup when rendering code changes.
- [ ] On the intended desktop, manually check kitty graphics, `fun-config`, idle detection, autostart, installation, and uninstall. Automated checks do not establish desktop or cross-distribution compatibility.
- [ ] On each additional distribution, check command availability, the `/usr/local` install layout, GTK4/PyGObject, terminal previews, and an idle backend before listing it as tested.
- [ ] Review the staged files and diff before a new commit. Create a new tag only when a new release is intended.

Generated previews and local development files are excluded from Git. Add screenshots only after checking that they show current scenes and contain no private desktop content.
