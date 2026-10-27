// SPDX-License-Identifier: MIT
// Device-specific shell geometry, selected from the descriptor installed by
// the device package. Values are logical pixels; QML passes them through
// Style.space() so the shell's configured spacing scale still applies.

var DESCRIPTOR_PATH = "/usr/share/omamobile/device.conf"

var DEFAULT_PROFILE = {
  codename: "",
  sideInset: 0,
  barScale: 1,
  cameraPillWidth: 0,
  cameraPillHeight: 0,
  cameraPillTop: 0,
  centerClearance: 0
}

var MYRON_PROFILE = {
  codename: "myron",
  sideInset: 12,
  barScale: 2,
  cameraPillWidth: 56,
  cameraPillHeight: 28,
  cameraPillTop: 6,
  centerClearance: 80
}

function codename(descriptor) {
  var lines = String(descriptor || "").split(/\r?\n/)
  for (var i = 0; i < lines.length; i++) {
    var match = lines[i].match(/^CODENAME=([a-z0-9]+)$/)
    if (match) return match[1]
  }
  return ""
}

function profile(descriptor) {
  return codename(descriptor) === "myron" ? MYRON_PROFILE : DEFAULT_PROFILE
}

function barSize(baseSize, selectedProfile) {
  var scale = selectedProfile && Number(selectedProfile.barScale)
  return Math.round(Number(baseSize) * (isFinite(scale) && scale > 0 ? scale : 1))
}

if (typeof module !== "undefined") module.exports = {
  DESCRIPTOR_PATH: DESCRIPTOR_PATH,
  DEFAULT_PROFILE: DEFAULT_PROFILE,
  MYRON_PROFILE: MYRON_PROFILE,
  codename: codename,
  profile: profile,
  barSize: barSize
}
