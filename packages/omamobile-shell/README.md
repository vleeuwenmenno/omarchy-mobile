# omamobile-shell

Omarchy Mobile's phone profile for Omarchy's own shell. It isn't a fork: these are ordinary Omarchy shell plugins plus a phone `shell.json`, linked into the user's config by `omamobile-setup-user`.

| Path | What it is |
| --- | --- |
| `plugins/omamobile.bar` | Phone status bar (a full `bar` plugin) |
| `plugins/omamobile.quicksettings` | Pull-down quick settings |
| `plugins/omamobile.launcher` | Home bar: app search, app grid and a prompt to the user's Omarchy default agent |
| `plugins/omamobile.switcher` | Bottom-edge gestures and recent apps: swipe up from the bottom edge to go home, swipe up and pause for recents, sideways to switch apps; hold a card to show the app with another one, or give it its own screen again |
| `plugins/omamobile.home` | Home screens: pages of apps and widgets on the wallpaper, with an edit mode. The built-ins include every widget in Simon Schubert's [omarchy-widgets](https://github.com/SimonSchubert/omarchy-widgets) `widgets/simonschubert/` (MIT): the OWL originals, from the `omamobile-owl-widgets` package, run by our own OWL runtime (`owl/`, see `owl/SPEC-NOTES.md`). `widgets/OWL.md` is his OWL language guide (MIT, `widgets/LICENSE-owl-guide`) |
| `plugins/omamobile.settings` | The Settings app (also an app in the drawer and a Quick Settings tile and gear): General (theme picker, rotation, about), Keyboard (automatic showing, portrait and landscape size, stretch, bottom gap) and Quick Settings (tile count, the existing editor, reset). Values come from `bin/omamobile-settings`; the launcher reads the shared `plugins/omamobile.launcher/SettingsGeometry.js` model |
| `plugins/omamobile.keyboard` | Hide button above the on-screen keyboard |
| `plugins/omamobile.update` | The update sheet: Omarchy's update for a phone, through `omamobile-update` (package `omamobile-omarchy`) |
| `plugins/omamobile.access` | The permission sheet: "Allow Camera to use the camera?" with the app's icon and two large buttons, in place of xdg-desktop-portal-gtk's desktop dialog |
| `plugins/omamobile.fingerprint` | The under-display fingerprint sensor: target during verification, enrollment screen |
| `profile/shell.json` | The phone layout the setup seeds once |
| `bin/omamobile-setup-user` | Omarchy Mobile's per-user setup (Omarchy lifecycle `setup-user`) |
| `bin/omamobile-launch` | One app per screen: every launch from the shell (drawer, home screen, widgets, links, the agent) gets a new empty workspace through a per-launch Hyprland exec rule, or focuses the app's open window; and the switcher's "Show with…" and "Move to its own screen" |
| `bin/omamobile-settings` | The Settings helper: `status`, `general`, validated `set`, `keyboard-auto reconcile` and `keyboard-theme generate\|install\|remove\|status` (Squeekboard's keys as Omarchy's square controls, from the theme, through a generated GTK 3 CSS file that `gtk.css` imports) |
| `bin/omamobile-osk-watch` | Reports squeekboard's visibility (sm.puri.OSK0) to the fingerprint plugin |
| `bin/omamobile-fp-enroll` | fprintd enrollment helper the fingerprint screen runs (JSON lines) |
| `bin/omamobile-bt-agent` | BlueZ pairing agent and discovery helper the quick-settings Bluetooth panel runs while open |
| `bin/omamobile-portal-access` | The xdg-desktop-portal Access backend (`org.freedesktop.impl.portal.desktop.omamobile`, a D-Bus-activated user unit) that shows the permission sheet and answers the portal |
| `portal/` | `omamobile.portal`, its D-Bus activation file, and `/etc/xdg-desktop-portal/hyprland-portals.conf`, which picks it for Access (the file chooser is the app profile's choice: its `/etc/xdg/xdg-desktop-portal/` file is read first; everything else stays `hyprland;gtk`) |
| `bin/omamobile-widget` | The user's own home-screen widgets: scan and check them, make one from the template, copy an example, remove one, start Omarchy's default agent in a widget's folder |
| `widgets/WIDGETS.md` | The contract for user widgets, for people and coding agents (installed to `/usr/share/omamobile/shell/`) |
| `widgets/template`, `widgets/examples` | The starter **Create a widget with AI** copies, and examples to copy (`widget-template/`, `widget-examples/`) |

## AI Agent shortcut

**AI Agent** in the app drawer opens Omarchy's default agent with
`omarchy-agent --pick`. If no agent is chosen, it opens the existing
**Setup > Default Agent** chooser, which installs the user's selection.
The shortcut does not choose or preinstall an agent. Existing choices are
preserved, and it can be added to a home screen like any other app.
Tapping it focuses the most recently used open agent window, including a
widget-building session, instead of starting another session. To start a
separate task, use Omarchy's normal agent command.
Foot and `xdg-terminal-exec` already ship in Omarchy's base package list,
which normal root images install. The explicit dependencies are a guard
for hand-built or partial installations: both agent launch and installing
a selection need Omarchy's terminal launcher.

## File dialogs

Open, save and choose-a-folder requests go to the file chooser the app profile picks: Strata on Myron (`omamobile-apps-myron`), Nautilus's libadwaita chooser from xdg-desktop-portal-gnome on the generic profile (`omamobile-apps`). Either folds its sidebar away at phone width; `hypr/phone.lua` tiles it, even with a parent window, so it fills the screen between the bar and the on-screen keyboard. Without a profile, xdg-desktop-portal-gtk (a dependency) serves it. Super+Shift+F and Super+Alt+Shift+F run `xdg-open` on the home or terminal directory, so the default folder handler opens, not a named file manager.

The package contract follows omarchy-mac's: `./install DESTDIR` stages files and enables nothing, `test/all` runs the package's own tests, and `version` holds the version.

Develop on a desktop with `phone/dev/run-desktop` from the repo root.
