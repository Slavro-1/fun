# Investigating a KDE idle blocker

On the Pop!_OS KDE X11 laptop, xprintidle advanced and reset on input.
PowerDevil reported a screen inhibition and listed “AC Screen Lock” with
the reason “Keep the session unlocked on AC power”. The active user unit
`ac-screen-lock.service` runs a Python helper that asks
`org.freedesktop.ScreenSaver.Inhibit` for exactly this request. Its journal
records release on battery and reacquisition on AC. The default charger-only
preference and this AC policy can leave no eligible time for automatic playback.

Use `fun-idle --diagnose` to distinguish the idle detector, lock state and
policy. On older Plasma versions PowerDevil lists all active requests together.
The list supplies context. The separate screen-policy query controls launch.
A manual `fun --scene koi` is available while automatic playback is held.

## Upstream attribution

The desktop also displayed a ChatGPT executable. An application label or a
forwarded D-Bus request alone cannot identify the original executable.
The independent AC helper accounts for persistence after the app preference
changed. A separate ChatGPT or PowerDevil bug would need a reproduction that
identifies the D-Bus sender and its request lifetime.
