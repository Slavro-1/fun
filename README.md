# fun

`fun` brings animated screensavers to a Linux terminal. Run one scene when you want a break, or let the launcher rotate through the built-in scenes every 10 minutes. A GTK4 settings window and an idle watcher are optional.

Scenes include aurora, koi, nebula, stained glass, and many more. `fun --list` shows the current active set. The launcher can also include classic terminal programs such as `cmatrix`, `nyancat`, and `sl` when they are installed.

You can choose scenes, rotation order, and quality; save preferences in the settings window; and optionally start a fullscreen saver after a period of inactivity.

## Gallery

Screenshots and animations will be added later.

## Requirements and environments

Developed and tested on **Pop!_OS 24.04 with KDE Plasma and kitty**. KDE is not required: `fun-config` is a GTK4 application that can run in other compatible graphical desktop sessions. Other distributions and desktop sessions have not been manually verified.

- **Core scenes:** Linux, Bash, Python 3.11 or newer, and a UTF-8 terminal. The Python renderer uses the standard library. A truecolor terminal gives the best half-block output.
- **Rotating launcher:** Common GNU/Linux tools including `readlink`, `timeout`, `nice`, `shuf`, `stty`, and `clear`. Optional terminal programs are used only when present; their package names vary by distribution.
- **Settings window:** GTK4 and PyGObject. Pillow is needed for scene thumbnails, but not for the renderer or saved settings. A graphical session and a terminal emulator are needed for previews.
- **Idle watcher:** Linux `/proc` and `/sys` facilities and a working idle detector. It tries readable `/dev/input/event*` devices, GNOME Mutter, `xprintidle` on X11, and systemd-logind. Availability depends on the session and permissions. The default fullscreen terminal is kitty; `FUN_TERMINAL` can supply another launch command.

The installer does not use apt or install packages. Debian, Fedora, Arch, and other Linux distributions may work when these requirements are met, but they have not been tested here. The installer uses `sudo` to write to `/usr/local` and creates launchers in your home directory.

## Install

Clone or download this repository. From its directory, run:

```bash
./install.sh
```

The installer checks syntax and the scenes before copying files. It places commands in `/usr/local/bin`, shared files in `/usr/local/lib/fun`, and a per-user idle autostart entry in your home directory. Existing program files and desktop entries receive timestamped backups. Review the script before running it. It does not install dependencies or change group membership.

To try the core scenes from the checkout without installing:

```bash
./fun --list
./fun --scene aurora
```

## Use

```bash
fun                                      # rotate scenes; Ctrl-C exits
fun --list                               # list active built-in scenes
fun --scene koi                          # run one scene; q or Ctrl-C exits
fun --minutes 5 --order sequential --scenes aurora,koi
fun --quality medium                     # low, medium, high, ultra, or auto
fun-config                               # open GTK4 settings
fun-idle --diagnose                      # check available idle detectors
fun-idle --status                        # show current idle conditions
fun-idle                                 # run the watcher directly
```

The idle watcher starts at login after installation when the desktop honors the autostart entry. By default, it launches after 13 idle minutes while charging, with the lid open and no competing idle inhibitor. Use `fun-idle --diagnose` before relying on it. Its default launch uses kitty; for another terminal, set `FUN_TERMINAL` to a command that starts `fun` in that terminal.

## Graphics and settings

In a local kitty session, `fun` uses the kitty graphics protocol when support is detected. In other terminals, tmux, screen, or SSH, the renderer uses Unicode half-blocks; truecolor support improves the result. Use `FUN_GFX=0 fun --scene koi` to force half-block output. `FUN_RES=low|med|high|ultra` sets graphics resolution, and `python3 extras.py --gfx-info` reports the detected path from the checkout.

`fun-config` saves scene selection, rotation interval, quality, and idle options in `~/.config/fun/settings.toml` by default, or under `$XDG_CONFIG_HOME/fun/` when set. The launcher reads settings at startup; the idle watcher reloads saved changes while running. Command-line options and `FUN_*` environment variables can override saved values.

## Troubleshooting

- If a scene or the launcher fails, run `fun --selftest` and check `~/.cache/fun/launcher.log` (or `$XDG_CACHE_HOME/fun/launcher.log`).
- If graphics do not appear in kitty, try a local kitty window outside tmux or screen. `FUN_GFX=0` checks the half-block path.
- If `fun-config` does not open, check GTK4, PyGObject, and the graphical session. Missing Pillow affects thumbnails only.
- If `fun-idle` does not start a saver, run `fun-idle --diagnose` and check `~/.cache/fun/idle.log`. Access to `/dev/input/event*` can require device permissions; another backend may work. The installer does not grant input access.
- After an abrupt terminal interruption, run `reset` if the display looks wrong.

## Uninstall

From the checkout, run `./uninstall.sh`. It removes installed program files and the desktop entries made by the installer. Saved settings, logs, and timestamped backups remain for review. Remove your `fun` directories under `~/.config` and `~/.cache` (or their XDG overrides) separately if you no longer want them.

## License

MIT. See [LICENSE](LICENSE).
