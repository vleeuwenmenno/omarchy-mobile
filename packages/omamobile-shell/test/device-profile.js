// SPDX-License-Identifier: MIT
const assert = require("assert")
const fs = require("fs")
const Profile = require("../plugins/DeviceProfile.js")

const myron = Profile.profile("# device\nCODENAME=myron\nNAME=POCO F8 Ultra\n")
assert.strictEqual(myron.sideInset, 12)
assert.strictEqual(Profile.barSize(44, myron), 88)
assert.deepStrictEqual(
  [myron.cameraPillWidth, myron.cameraPillHeight, myron.cameraPillTop, myron.centerClearance],
  [56, 28, 6, 80]
)

for (const descriptor of ["", "CODENAME=cheetah\n", "CODENAME=felix\n", " CODENAME=myron\n"]) {
  const common = Profile.profile(descriptor)
  assert.strictEqual(common.sideInset, 0)
  assert.strictEqual(Profile.barSize(44, common), 44)
  assert.strictEqual(common.cameraPillWidth, 0)
  assert.strictEqual(common.centerClearance, 0)
}

const bar = fs.readFileSync("plugins/omamobile.bar/Bar.qml", "utf8")
const launcher = fs.readFileSync("plugins/omamobile.launcher/Launcher.qml", "utf8")
assert.match(bar, /objectName: "myronCameraPill"/)
assert.match(bar, /visible: root\.deviceProfile\.codename === "myron"/)
assert.match(bar, /anchors\.leftMargin: Style\.spacing\.huge \+ root\.sideInset/)
assert.match(bar, /anchors\.rightMargin: Style\.spacing\.huge \+ root\.sideInset/)
assert.match(bar, /readonly property int barSize: DeviceProfile\.barSize\(baseBarSize, deviceProfile\)/)
assert.match(launcher, /anchors\.leftMargin: Style\.spacing\.xxl \+ root\.sideInset/)
assert.match(launcher, /anchors\.rightMargin: Style\.spacing\.xxl \+ root\.sideInset/)

console.log("ok - Myron safe-area profile and shell wiring")
