# fun

`fun` is a collection of animated terminal screensavers for Linux. It rotates through 41 built-in Python scenes and, when installed, can also include classic terminal programs such as `cmatrix`, `nyancat`, and `sl`. The launcher switches scenes every 10 minutes by default. A GTK settings app and an optional idle watcher make it suitable for a desktop session.

## Features and terminal support

- Animated scenes with color, motion, and terminal cleanup on exit.
- Kitty graphics protocol when a local kitty session confirms support; RGB images use shared memory when possible and compressed transfer otherwise.
- Truecolor Unicode half-block fallback in other terminals, tmux, screen, and SSH sessions. Set `FUN_GFX=0` to force it.
- Scene selection, random or sequential order, quality settings, and saved preferences.
- Optional idle launch that checks user activity, lid, charging state, and other idle inhibitors.

Developed for Pop!_OS with COSMIC and kitty. The renderer and command-line launcher target Linux terminals; `fun-idle` uses Linux and desktop-session facilities. Other distributions and terminals may work, especially with half-block output. A truecolor terminal gives the best fallback appearance.

## Gallery

Screenshots are intentionally left as placeholders for this first release; generated development previews have not been included in the distribution.

| Scene | Screenshot |
| --- | --- |
| Aurora | Screenshot coming soon |
| Koi | Screenshot coming soon |
| Nebula | Screenshot coming soon |
| Stained Glass | Screenshot coming soon |
| Silk | Screenshot coming soon |
| Metropolis | Screenshot coming soon |

Run `fun --list` for the current complete scene inventory.

## Requirements

- Linux, Bash, Python **3.11 or newer** (for `tomllib`), and a UTF-8 terminal. Python 3.12 is the tested development version.
- The launcher uses common GNU/Linux commands including `timeout`, `nice`, `shuf`, `stty`, and `clear`. `systemd-inhibit` and GNOME `gsettings` are used when available to manage idle and sleep behavior.
- **Kitty** is recommended for graphics and required by the default `fun-idle` launch command. Set `FUN_TERMINAL` to a suitable custom command if using another terminal.
- **GTK 4 / PyGObject** is needed only for `fun-config`. **Pillow** is needed only to generate its scene thumbnails; the renderer itself uses Python's standard library and does not require NumPy.
- Optional rotation programs are skipped if absent: `cmatrix`, `asciiquarium`, `cbonsai`, `pipes.sh`, `nyancat`, `cacafire`, `cacademo`, `aafire`, `tty-clock`, `cowsay`, `fortune`, `lolcat`, and `sl`. Install these separately if wanted; their availability and package names vary by distribution.

## Install

Clone or download this repository, then from its directory:

```bash
./install.sh
```

The installer checks syntax and all Python scenes before using `sudo`. It places programs in `/usr/local/bin`, shared files in `/usr/local/lib/fun`, and desktop launchers in your home directory. Existing program and launcher files receive timestamped backups. Review the script before running it. It does not install dependencies for you.

To try the project from the checkout without installing:

```bash
./fun --list
./fun --scene aurora
```

`fun-idle --diagnose` reports the available idle detector. On some Wayland systems, reading `/dev/input/event*` needs membership in the `input` group. That group grants access to raw input events; add yourself only if you want that backend and understand the access, then log out and back in. The installer does not change group membership.

## Use

```bash
fun                         # rotate scenes; Ctrl-C exits
fun --list                  # active Python scene names
fun --scene koi             # one scene; q or Ctrl-C exits
fun --test 5                # run each Python scene for 5 seconds in this terminal
fun --selftest              # headless renderer check
fun --minutes 5 --order sequential --scenes aurora,koi
fun --quality medium        # low, medium, high, ultra, or auto
fun-config                  # GTK settings window
fun-idle --diagnose         # inspect idle detection
fun-idle --status           # show current idle conditions
fun-idle                    # run watcher directly
```

The settings app saves duration, order, quality, enabled scenes, and idle options in `${XDG_CONFIG_HOME:-~/.config}/fun/settings.toml`. The launcher reads this file at startup; the idle watcher picks up saved changes while running. Command-line options and `FUN_*` environment variables can override saved launcher values. By default, `fun-idle` starts after 13 idle minutes while charging, with the lid open and no competing idle inhibitor. The installer adds a per-user autostart entry.

The built-in Python scenes participate in rotation alongside any installed optional terminal programs. Use `--scenes` or the settings app to choose Python scenes. `FUN_MINUTES=20 fun` changes the interval; `FUN_ONLY='python3' fun` limits rotation to matching launcher commands. `FUN_NO_POWER=1 fun` disables the launcher's GNOME power-setting changes.

## Graphics and troubleshooting

Use `FUN_GFX=0 fun --scene koi` for half-block output. `FUN_RES=low|med|high|ultra` controls graphics resolution (`ultra` is the default). `python3 extras.py --gfx-info` shows the detected graphics path in a terminal. If kitty graphics does not appear, try a local kitty session outside tmux/screen, then check the fallback with `FUN_GFX=0`.

If the idle watcher does not start, run `fun-idle --diagnose` and check `~/.cache/fun/idle.log`. If a scene fails during rotation, check `~/.cache/fun/launcher.log`. If the settings window does not open, check GTK 4, PyGObject, and the graphical session; thumbnail generation additionally requires Pillow. `fun --selftest` works without a graphical terminal. Use `Ctrl-C` or `q` to exit a scene; if a terminal was interrupted hard, run `reset`.

## Uninstall

From the checkout, run `./uninstall.sh`. It removes the installed programs and the desktop entries created by the installer. Saved settings, caches, and timestamped backups are kept for review. Remove `${XDG_CONFIG_HOME:-~/.config}/fun` and `${XDG_CACHE_HOME:-~/.cache}/fun` manually if you want to discard personal settings and logs. If you manually joined the `input` group, undo that separately after considering other programs that use it.

## License

MIT; see [LICENSE](LICENSE).
