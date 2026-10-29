#!/bin/bash
# SPDX-License-Identifier: MIT
# Settings app wiring: where it is reachable, what it must not do, and the
# keyboard tile / automatic-show semantics, checked in the sources.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
fail() { printf 'not ok - %s\n' "$1" >&2; exit 1; }
qs=plugins/omamobile.quicksettings/QuickSettings.qml

# Reachable: profile, setup migration, drawer entry, quick settings (tile and gear).
python3 -c 'import json; assert {"id": "omamobile.settings"} in json.load(open("profile/shell.json"))["plugins"]' || fail "the profile enables Settings"
grep -Fq 'add_plugin omamobile.settings' bin/omamobile-setup-user || fail "setup switches Settings on for existing profiles"
grep -Fq 'Exec=omarchy-shell shell summon omamobile.settings' applications/omamobile-settings.desktop || fail "the drawer entry summons Settings"
grep -Fq 'applications/omamobile-settings.desktop' install || fail "the desktop entry is installed"
grep -Fq 'hooks/omamobile-keyboard-theme' install || fail "the theme hook is installed"
grep -Fq '"settings": settingsTile' "$qs" || fail "Settings has a quick settings tile"
grep -Fq 'omamobile.settings' "$qs" || fail "quick settings opens Settings"

# Not above the lock, and never takes keyboard focus.
if grep -n 'omamobile-settings' hypr/phone.lua | grep -q above_lock; then fail "Settings is not drawn above the lock"; fi
grep -Fq 'WlrLayershell.keyboardFocus: WlrKeyboardFocus.None' plugins/omamobile.settings/Settings.qml || fail "Settings never takes keyboard focus"
grep -Fq "lock status" plugins/omamobile.settings/Settings.qml || fail "Settings refuses to open over a secure lock"
grep -Fq 'pocket.active' plugins/omamobile.settings/Settings.qml || fail "Settings refuses to open in a pocket"

# One Keyboard tile: the manual show/hide, with its Settings page behind the chevron.
[[ $(grep -c '^    id: keyboard$' "$qs") -eq 1 ]] || fail "exactly one keyboard tile backend"
[[ $(grep -c 'id: "keyboard"' plugins/omamobile.quicksettings/TilesModel.js) -eq 1 ]] || fail "exactly one keyboard tile in the catalog"
awk '/id: keyboard$/,/id: keyboardRead/' "$qs" > /tmp/keyboard-tile.$$
trap 'rm -f /tmp/keyboard-tile.$$' EXIT
grep -Fq 'readonly property bool details: true' /tmp/keyboard-tile.$$ || fail "the keyboard tile has a chevron"
grep -Fq 'root.openSettings("keyboard")' /tmp/keyboard-tile.$$ || fail "the keyboard chevron opens Settings > Keyboard"
if grep -Fq 'show ? "true"' /tmp/keyboard-tile.$$; then fail "the tile no longer asks for a show before the sheet closes"; fi
python3 - /tmp/keyboard-tile.$$ <<'PY' || fail "the keyboard tile closes the sheet before it asks for the keyboard"
import re, sys
t = open(sys.argv[1]).read()
i = t.index("function toggle()")
body = t[i:i + 900]
assert body.index("root.dismiss()") < body.index("keyboardShowLater.restart()")
assert "SetVisible" not in body.split("root.dismiss()")[1].split("}")[0]
PY
grep -Fq 'keyboardPocket.active' "$qs" || fail "the delayed show respects pocket protection"
grep -Fq "lock status" "$qs" || fail "the delayed show respects the lock"
# The tile does not depend on the automatic preference.
if sed -n '/id: keyboard$/,/id: keyboardRead/p' "$qs" | grep -Fq 'screen-keyboard-enabled'; then fail "the manual tile is independent of auto-show"; fi

# Automatic showing is the user's choice: no login or setup step forces it on.
if grep -n 'screen-keyboard-enabled' hypr/phone.lua | grep -v '^[0-9]*:--' | grep -q .; then fail "login does not force automatic showing on"; fi
grep -Fq 'omamobile-settings keyboard-auto reconcile' hypr/phone.lua || fail "login only undoes the screensaver's own switch-off"
[[ $(grep -c 'screen-keyboard-enabled' bin/omamobile-setup-user) -eq 1 ]] || fail "setup mentions the preference once"
python3 - <<'PY' || fail "setup sets automatic showing only in its once-only first step"
import re
s = open("bin/omamobile-setup-user").read()
m = re.search(r'if omarchy-done ensure omamobile-osk; then(.*?)\nfi\n', s, re.S)
assert m and "screen-keyboard-enabled true" in m.group(1)
assert s.count("screen-keyboard-enabled") == 1
PY
grep -Fq 'Automatically show when typing' plugins/omamobile.settings/Settings.qml || fail "Settings has the automatic showing switch"
grep -Fq '"keyboard.auto_show"' plugins/omamobile.settings/Settings.qml || fail "the switch is backed by the helper's auto_show"
grep -Fq -- '--enable-wayland-ime' bin/omamobile-setup-user || fail "Chromium gets its Wayland IME flag"
echo 'ok - Settings wiring'
