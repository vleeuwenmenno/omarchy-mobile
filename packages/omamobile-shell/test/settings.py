# SPDX-License-Identifier: MIT
"""omamobile-settings: validation, atomic file, GSettings preservation, keyboard theme."""
import importlib.machinery
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "bin/omamobile-settings"

loader = importlib.machinery.SourceFileLoader("omamobile_settings", str(TOOL))
spec = importlib.util.spec_from_loader("omamobile_settings", loader)
M = importlib.util.module_from_spec(spec)
loader.exec_module(M)

FAKE = r'''#!/usr/bin/env python3
import json, os, sys
path = os.environ["FAKE_GSETTINGS_DB"]
db = json.load(open(path))
op, schema, key, *rest = sys.argv[1:]
full = schema + " " + key
if full not in db:
    sys.exit(1)
if op == "get":
    print(db[full])
else:
    db[full] = rest[0]
    json.dump(db, open(path, "w"))
'''


def fail(message):
    print("not ok - " + message)
    sys.exit(1)


def check(condition, message):
    if not condition:
        fail(message)


def run(env, *args):
    result = subprocess.run([sys.executable, "-B", str(TOOL), *args], env=env, capture_output=True, text=True)
    try:
        data = json.loads(result.stdout)
    except ValueError:
        data = None
    return result.returncode, data


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    fake = tmp / "gsettings"
    fake.write_text(FAKE)
    fake.chmod(0o755)
    db = tmp / "db.json"
    db.write_text(json.dumps({
        "sm.puri.Squeekboard scale-in-vertical-screen-orientation": "1.8",
        "sm.puri.Squeekboard scale-in-horizontal-screen-orientation": "1.0",
        "sm.puri.Squeekboard layout-shape-changes-to-fit-panel": "true",
        "org.gnome.desktop.a11y.applications screen-keyboard-enabled": "true",
    }))
    runtime = tmp / "run"
    runtime.mkdir()
    env = dict(os.environ, HOME=str(tmp), OMAMOBILE_SETTINGS_FILE=str(tmp / "config/settings.json"),
               OMAMOBILE_GSETTINGS=str(fake), FAKE_GSETTINGS_DB=str(db), OMAMOBILE_RUNTIME_DIR=str(runtime),
               OMAMOBILE_GTK_DIR=str(tmp / "gtk-3.0"), OMAMOBILE_THEME_DIR=str(tmp / "theme"))
    settings_file = tmp / "config/settings.json"

    # Existing values are read, never reset; the gap defaults.
    code, st = run(env, "status")
    check(code == 0 and st["keyboard"] == {"portrait_scale": 1.8, "landscape_scale": 1.0, "stretch": True,
                                           "auto_show": True, "bottom_gap": 24}, "status reports the live values")
    check(not settings_file.exists(), "status writes nothing")
    check(st["limits"] == {"scale": [0.5, 2.0], "gap": [24, 64], "gap_default": 24}, "limits are reported")

    # No schemas: unavailable, not an error; the gap still works.
    bare = dict(env, OMAMOBILE_GSETTINGS=str(tmp / "missing"))
    code, st = run(bare, "status")
    check(code == 0 and st["available"] == {"size": False, "stretch": False, "auto_show": False}, "no schema is reported as unavailable")
    code, out = run(bare, "set", "keyboard.portrait_scale", "1.2")
    check(code == 1 and "error" in out, "a size cannot be set without the schema")

    # Validated writes.
    for key, value in (("keyboard.bottom_gap", "23"), ("keyboard.bottom_gap", "65"), ("keyboard.bottom_gap", "abc"),
                       ("keyboard.bottom_gap", "30.5"), ("keyboard.bottom_gap", "-30"),
                       ("keyboard.portrait_scale", "0.49"), ("keyboard.portrait_scale", "2.01"),
                       ("keyboard.landscape_scale", "nan"), ("keyboard.landscape_scale", "x"),
                       ("keyboard.stretch", "maybe"), ("keyboard.nothing", "1")):
        code, out = run(env, "set", key, value)
        check(code == 1 and "error" in out, "rejects %s=%s" % (key, value))
    check(not settings_file.exists(), "rejected values write nothing")
    check(json.loads(db.read_text())["sm.puri.Squeekboard scale-in-vertical-screen-orientation"] == "1.8", "rejected values leave GSettings alone")

    code, st = run(env, "set", "keyboard.bottom_gap", "40")
    check(code == 0 and st["keyboard"]["bottom_gap"] == 40, "gap saved")
    data = json.loads(settings_file.read_text())
    check(data == {"version": 1, "keyboard": {"bottom_gap": 40}}, "the file is the validated document")
    check(stat.S_IMODE(settings_file.stat().st_mode) == 0o644, "the file is readable by the shell")
    check(not [p for p in settings_file.parent.iterdir() if p.name.startswith(".settings.json.")], "no temporary file is left")
    check(M.clamp_gap(24) == 24 and M.clamp_gap(999) == 64 and M.clamp_gap(-5) == 24 and M.clamp_gap("x") == 24
          and M.clamp_gap(float("nan")) == 24, "the reader clamps a hand-edited file")

    # A hand-edited file keeps unknown keys; an unreadable one is kept aside.
    settings_file.write_text(json.dumps({"version": 1, "extra": {"a": 1}, "keyboard": {"bottom_gap": 999, "other": 2}}))
    code, st = run(env, "status")
    check(st["keyboard"]["bottom_gap"] == 64, "out-of-range file values are clamped when read")
    run(env, "set", "keyboard.bottom_gap", "48")
    data = json.loads(settings_file.read_text())
    check(data["extra"] == {"a": 1} and data["keyboard"] == {"bottom_gap": 48, "other": 2}, "unknown keys survive a write")
    settings_file.write_text("{ not json")
    code, st = run(env, "status")
    check(code == 0 and st["keyboard"]["bottom_gap"] == 24, "an unreadable file reads as the default")
    run(env, "set", "keyboard.bottom_gap", "32")
    check(json.loads(settings_file.read_text())["keyboard"]["bottom_gap"] == 32
          and list(settings_file.parent.glob("settings.json.invalid-*")), "an unreadable file is kept aside, not overwritten")

    # Sizes and stretch go to GSettings, one key at a time; the other keeps its value.
    code, st = run(env, "set", "keyboard.landscape_scale", "1.35")
    kb = st["keyboard"]
    check(kb["landscape_scale"] == 1.35 and kb["portrait_scale"] == 1.8, "landscape changes alone")
    code, st = run(env, "set", "keyboard.stretch", "false")
    check(st["keyboard"]["stretch"] is False and st["keyboard"]["portrait_scale"] == 1.8, "stretch changes alone")
    check(json.loads(db.read_text())["sm.puri.Squeekboard layout-shape-changes-to-fit-panel"] == "false", "stretch reached GSettings")

    # Auto-show: the user's Off survives every other write, the theme install and login reconcile.
    marker = runtime / "omarchy-screensaver-osk-off"
    code, st = run(env, "set", "keyboard.auto_show", "false")
    check(st["keyboard"]["auto_show"] is False, "auto-show switched off")
    for args in (("set", "keyboard.bottom_gap", "56"), ("set", "keyboard.portrait_scale", "1.4"),
                 ("keyboard-theme", "install"), ("keyboard-auto", "reconcile")):
        run(env, *args)
        check(run(env, "status")[1]["keyboard"]["auto_show"] is False, "auto-show stays off after " + " ".join(args))
    code, out = run(env, "keyboard-auto", "reconcile")
    check(out["action"] == "none", "no marker: reconcile leaves the user's Off alone")

    # A screensaver marker with nothing running means the screensaver never restored it.
    run(env, "set", "keyboard.auto_show", "true")
    marker.write_text("")
    run(env, "set", "keyboard.auto_show", "false")
    check(not marker.exists(), "an explicit choice clears a pending screensaver restore")
    check(run(env, "keyboard-auto", "reconcile")[1]["action"] == "none" and
          run(env, "status")[1]["keyboard"]["auto_show"] is False, "explicit Off wins over a stale marker")
    marker.write_text("")
    code, out = run(env, "keyboard-auto", "reconcile")
    check(out["action"] == "restored" and run(env, "status")[1]["keyboard"]["auto_show"] is True and not marker.exists(),
          "a stale screensaver marker is undone once")

    # Keyboard theme: only sq_* selectors, readable pairs, idempotent import with backup.
    theme = tmp / "theme"
    theme.mkdir()
    (theme / "colors.toml").write_text('background = "#1a1b26"\nforeground = "#a9b1d6"\naccent = "#7aa2f7"\nbright_foreground = "#c0caf5"\n')
    (theme / "shell.toml").write_text('[bar]\nbackground = "#1a1b26"\ntext = "#a9b1d6"\n[controls]\nnormal-fill-alpha = 0.04\nnormal-border-alpha = 0.4\nnormal-border-width = 1\n')
    css = M.keyboard_css()
    selectors = [line.rstrip(" {,") for line in css.splitlines() if line and not line.startswith((" ", "/*", "}", "   ", "Do ", "own"))]
    check(selectors and all(re.match(r"^(sq_view|sq_button|#Return)", s) for s in selectors), "only sq_* and #Return selectors: %r" % selectors)
    check("border-radius: 0;" in css and "gtk-" not in css and "@define" not in css, "square keys, no global rules")

    def pairs(p):
        bg, fg, accent = p["background"], p["foreground"], p["accent"]
        pressed = M.blend(bg, accent, max(p["pressed_alpha"], 0.30))
        latched = M.blend(bg, accent, max(p["selected_alpha"], 0.18) + 0.12)
        key = M.blend(bg, fg, max(p["fill_alpha"], 0.06))
        return [(key, fg), (pressed, M.readable_on(pressed, fg, p["bright"], bg)),
                (latched, M.readable_on(latched, fg, p["bright"], bg)), (accent, M.readable_on(accent, bg, fg, p["bright"]))]

    light = dict(M.palette(), background="#fbf1c7", foreground="#3c3836", accent="#076678", bright="#282828")
    for p in (M.palette(), light):
        for fill, text in pairs(p):
            check(M.contrast(fill, text) >= 4.5, "readable %s on %s" % (text, fill))

    gtk = tmp / "gtk-3.0"
    run(env, "keyboard-theme", "remove")
    (gtk / "gtk.css").unlink(missing_ok=True)
    code, out = run(env, "keyboard-theme", "install")
    check(code == 0 and out["import"] == "added" and out["backup"] is None, "install with no gtk.css creates it, no backup needed")
    check((gtk / "omamobile-squeekboard.css").read_text() == css, "generated file written")
    check((gtk / "gtk.css").read_text() == M.BLOCK, "gtk.css holds only the import block")
    run(env, "keyboard-theme", "remove")
    check(not (gtk / "gtk.css").read_text().strip() and not (gtk / "omamobile-squeekboard.css").exists(), "remove undoes it")

    original = "/* mine */\n@import url(\"other.css\");\nwindow { color: red; }\n"
    (gtk / "gtk.css").write_text(original)
    code, out = run(env, "keyboard-theme", "install")
    check(out["import"] == "added" and out["backup"] and Path(out["backup"]).read_text() == original, "install backs up an existing gtk.css")
    check((gtk / "gtk.css").read_text() == M.BLOCK + original, "the user's content follows the import untouched")
    backups = sorted(gtk.glob("gtk.css.omamobile-backup-*"))
    before = (gtk / "gtk.css").read_text()
    code, out = run(env, "keyboard-theme", "install")
    check(out["import"] == "unchanged" and out["generated"] == "unchanged" and out["backup"] is None, "second install changes nothing")
    check((gtk / "gtk.css").read_text() == before and sorted(gtk.glob("gtk.css.omamobile-backup-*")) == backups, "no new backup when nothing changed")
    (theme / "colors.toml").write_text('background = "#fbf1c7"\nforeground = "#3c3836"\naccent = "#076678"\n')
    (theme / "shell.toml").unlink()
    code, out = run(env, "keyboard-theme", "install")
    check(out["generated"] == "written" and out["import"] == "unchanged", "a theme change rewrites only the generated file")
    check("#fbf1c7" in (gtk / "omamobile-squeekboard.css").read_text(), "the new theme's colors are used")
    # An import that slipped below other rules is moved to the top.
    (gtk / "gtk.css").write_text(original + M.BLOCK)
    code, out = run(env, "keyboard-theme", "install")
    check(out["import"] == "moved" and (gtk / "gtk.css").read_text() == M.BLOCK + original and out["backup"], "a misplaced import is moved, with a backup")
    run(env, "keyboard-theme", "remove")
    check((gtk / "gtk.css").read_text() == original, "remove leaves exactly the user's file")

    # A symlinked gtk.css (dotfiles) stays a symlink.
    real = tmp / "dotfiles/gtk.css"
    real.parent.mkdir()
    real.write_text(original)
    (gtk / "gtk.css").unlink()
    (gtk / "gtk.css").symlink_to(real)
    run(env, "keyboard-theme", "install")
    check((gtk / "gtk.css").is_symlink() and real.read_text() == M.BLOCK + original, "a symlinked gtk.css is edited in place")

print("ok - omamobile-settings")
