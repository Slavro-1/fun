# fun

Little worlds for your Linux terminal. Pick a scene, or let `fun` wander through all 41 of them.

![Animated koi swimming among lily pads in fun](assets/motion/koi.gif)

## Quick install

Open a terminal as your usual desktop user and run:

```bash
git clone https://github.com/Slavro-1/fun.git
cd fun
./install.sh
```

The installer lists which dependencies are present and which are missing. On Debian, Ubuntu, Pop!_OS, Fedora, and Arch Linux, it shows the package command and asks for your permission before running it. Enter `y` to approve or press **Enter** to skip a prompt. It uses `sudo` for approved package commands and to copy the program files into `/usr/local`, so you may be asked for your password.

The full installation needs system Python 3.11 or newer and GTK4 with PyGObject. If you skip a required package or the import still fails, setup stops before copying program files. Pillow adds thumbnails in the settings window, and kitty provides the graphics mode. You can skip either recommendation and finish setup.

After setup, start the screensaver:

```bash
fun
```

Press **Ctrl+C** to leave. Open the settings window with `fun-config`.

## A few places to drift

There are quiet scenes, bright ones, and a few surprises. `fun` changes scenes every 10 minutes by default. You can also choose a favorite with `fun --scene aurora` or see every available scene with `fun --list`.

<p align="center">
  <img src="assets/gallery/aurora.png" alt="Aurora over a mountain skyline" width="48%">
  <img src="assets/gallery/stainedglass.png" alt="Colorful stained glass window" width="48%">
  <br><sub>Aurora · Stained glass</sub>
</p>
<p align="center">
  <img src="assets/gallery/jellyfish.png" alt="Glowing jellyfish in deep water" width="48%">
  <img src="assets/gallery/lanterns.png" alt="Floating lanterns reflected on a lake" width="48%">
  <br><sub>Jellyfish · Lanterns</sub>
</p>
<p align="center">
  <img src="assets/gallery/nebula.png" alt="Colorful nebula and stars" width="48%">
  <img src="assets/gallery/silk.png" alt="Flowing luminous silk strands" width="48%">
  <br><sub>Nebula · Silk</sub>
</p>

More motion, straight from the renderer:

<p align="center">
  <img src="assets/motion/nebula.gif" alt="Animated nebula" width="48%">
  <img src="assets/motion/silk.gif" alt="Animated luminous silk" width="48%">
</p>

## Make it yours

Run `fun-config` to choose scenes, rotation order, quality, and idle behavior. It saves your choices for the next launch.

<p align="center"><img src="assets/fun-config.png" alt="The real fun-config GTK4 settings window with the scene list populated" width="700"></p>

Useful shortcuts:

```bash
fun --scene koi       # stay with one scene; press q or Ctrl+C to leave
fun --list            # see all built-in scenes
fun --quality medium  # choose low, medium, high, or ultra
```

## Automatic idle activation

Enable **Activate on idle** in `fun-config`, set the delay and charging preference, then **Save / Apply**. The factory idle delay is **13 minutes**. A saved five-minute delay means five minutes. `FUN_IDLE_MIN`, `FUN_IDLE_ENABLED` and `FUN_IDLE_CHARGING_ONLY` override saved values in the watcher's environment. The separate scene rotation interval defaults to ten minutes. The existing `FUN_IDLE_NO_AC` and `FUN_IDLE_NO_LID` power overrides still apply. Automatic idle activation always honors inhibitors, including when the old `FUN_IDLE_NO_INHIBIT` variable is present.

After installing or upgrading, **log out and back in**. The installer updates one per-user XDG autostart entry. The desktop starts the enabled watcher in the graphical login environment. On desktops with an active systemd graphical-session target, that entry starts a transient user service tied to logout, with bounded restart attempts. Other XDG-autostart desktops run the watcher directly. Saving a disabled setting stops it. Enabling it in the GUI starts it again. A bare compositor needs an XDG autostart runner to launch desktop entries.

| Graphical session | Idle source and requirements |
| --- | --- |
| Plasma Wayland, compatible wlroots compositors | Prefers the compositor's advertised `ext_idle_notifier_v1` and a single identifiable seat. Subscribes at the configured delay and listens for `idled` and `resumed`. Compositor inhibitors apply. No compiler, input-device access or optional Python binding is needed. |
| GNOME Wayland | Uses native idle notifications if advertised, otherwise the Mutter idle counter on the session bus. |
| Plasma and other X11 desktops | Uses an advancing `xprintidle` counter on the native X display. Install the distribution's `xprintidle` package if needed. GNOME X11 first tries Mutter. Already-readable input devices are a legacy X11 fallback after actual input is seen. |
| Only logind hints available | Some desktops never update the hint. The watcher withholds activation until it observes both timestamped idle and active transitions. Timing then starts at the desktop's idle hint, so activation can be later than the configured delay. `--diagnose` reports an unverified hint as a limitation. |

Automatic activation requires a local graphical logind session whose active and lock state can be identified, plus `loginctl` and `busctl` with JSON output. A session with ambiguous identity or unreadable required policy data is unsuitable. The watcher checks logind idle blockers, KDE PowerDevil screen policy and GNOME idle inhibition where applicable. Wayland compositors can suppress an idle event without identifying the inhibiting app. Watcher-launched screensavers leave locking and suspend under desktop control. An earlier desktop lock or suspend can therefore prevent activation. Input-device permissions do not need to change.

Kitty is the default terminal. A `FUN_TERMINAL` override is the **entire foreground launch command**, including `fun`. Configure it in the desktop login environment. A command that detaches or hands the window to an existing terminal server cannot provide reliable child ownership. To test a terminal independently, run:

```bash
FUN_TERMINAL='xterm -fullscreen -e /usr/local/bin/fun' fun-idle --now
```

### Check a Debian Plasma Wayland login

1. From the reviewed checkout, run `./install.sh` as your desktop user. Log out, choose **Plasma (Wayland)** and log in again.
2. In `fun-config`, enable idle activation and save your normal delay (for example, five minutes). Open the lid and connect AC if charging-only is enabled.
3. In a graphical terminal, run `fun-idle --diagnose`. Check for **KDE / wayland**, **Watcher: running**, the expected terminal and delay, and a native subscription. If an application is inhibiting idle, finish that activity and check again.
4. Run `fun-idle --test` and leave keyboard, mouse and touchpad untouched. The login watcher temporarily uses ten seconds. Check that one fullscreen window appears, then move the mouse. Verify that it closes promptly and the test prints **PASS**. Ctrl+C cancels the test. It never writes settings.
5. Run `fun-idle --status` and confirm the normal delay has returned. Leave the laptop untouched for that full interval and verify one automatic launch and dismissal again. Repeat on Pop!_OS, checking which session and backend it actually reports.

`fun-idle --trace` follows timestamped login, backend, launch, dismissal and failure messages. `--now` tests the terminal and renderer only. If a watcher is missing, check for a **desktop startup invoked** line at login and the login entry in `--diagnose`. For a supervised watcher, inspect `journalctl --user -b -u 'fun-idle-*.service'`. Terminal errors are in `${XDG_CACHE_HOME:-~/.cache}/fun/saver.err`. Desktop acceptance requires a visible launch and dismissal on the machine being tested. The automated protocol, policy and lifecycle fixtures exercise those paths headlessly.

## Try it first, or download a ZIP

To try a scene from the downloaded folder without installing, run `./fun --scene aurora`. You can also run `./fun --list` to browse the names.

No Git? On this repository's GitHub page, choose **Code → Download ZIP**, extract it, open a terminal in the extracted `fun-main` folder, and run `bash install.sh`. Then use `fun` and `fun-config` as above.

## Requirements and terminal support

**For the screensavers:** Linux, Bash, Python 3.11 or newer, a UTF-8 terminal, and standard GNU/Linux command-line tools. The scene renderer uses the Python standard library. A truecolor terminal gives the best text-mode colors.

**For the settings window:** GTK 4.8 or newer and PyGObject for `/usr/bin/python3`. Pillow for the same interpreter adds thumbnails. The installer probes that interpreter even if a virtual environment is active.

**For automatic idle start:** See the session requirements above. GTK is used by the settings window. The watcher uses Python's standard library and Linux session interfaces.

`fun` uses kitty graphics automatically in a local kitty window. Other terminals use Unicode half-blocks. You can also force that mode with `FUN_GFX=0 fun --scene koi`. The project was developed and tested on Pop!_OS 24.04 with KDE Plasma and kitty.

If you prefer to install dependencies yourself, use the packages for your distribution with its package manager, then rerun `./install.sh`.

| Distribution | Required packages for system Python and the GUI | Recommended packages |
| --- | --- | --- |
| Debian, Ubuntu, Pop!_OS (`apt`) | `python3 python3-gi gir1.2-gtk-4.0` | `python3-pil kitty` |
| Fedora (`dnf`) | `python3 python3-gobject gtk4` | `python3-pillow kitty` |
| Arch Linux (`pacman`) | `python python-gobject gtk4` | `python-pillow kitty` |

On other distributions, install system Python 3.11 or newer, PyGObject for that system Python, and the GTK 4.8 or newer runtime and introspection data. The installer prints commands to verify the imports. If APT reports missing indexes or download errors, run `sudo apt update` and retry.

## If something goes wrong

- Run `fun --selftest` to check the built-in scenes. Launcher messages go to `~/.cache/fun/launcher.log`.
- If kitty graphics do not appear, try a local kitty window outside tmux or screen, or use `FUN_GFX=0 fun --scene koi`.
- If `fun-config` does not open, run it from a terminal in your graphical session to see the error. Rerun `./install.sh` to check the GTK4 and PyGObject imports.
- If idle startup does not work, run `fun-idle --diagnose`; idle detection and input access vary by session.
- If an interrupted scene leaves the terminal looking odd, run `reset`.

## Uninstall

From the downloaded project folder, run `./uninstall.sh` (or `bash uninstall.sh` from a ZIP). This removes installed program files and desktop entries. It keeps saved settings, logs, and timestamped backups. System packages are managed separately by your distribution's package manager.

## License

MIT. See [LICENSE](LICENSE).
