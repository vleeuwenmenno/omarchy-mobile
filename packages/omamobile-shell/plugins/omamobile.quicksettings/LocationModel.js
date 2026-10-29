// SPDX-License-Identifier: MIT
// Pure helpers for the Location tile and LocationPanel.qml, tested under Node
// (test/location-model.js). They read what `omamobile-location` prints; the
// observer behind it decides what this user may see.

var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

var END_LABELS = {
  "stopped": "Stopped",
  "client-exited": "App exited",
  "geoclue-restarted": "Location service restarted",
  "geoclue-stopped": "Location service stopped",
  "monitor-stopped": "Monitoring stopped",
  "monitor-restarted": "End time unknown",
  "events-lost": "Monitoring interrupted · end time unknown",
  "uncertain": "End time unknown"
}

// The JSON of one `omamobile-location` call, or null when it is not usable.
function parse(text) {
  try {
    var data = JSON.parse(String(text || "").trim())
    return data && typeof data === "object" && data.available === true ? data : null
  } catch (error) {
    return null
  }
}

function count(list) {
  return Array.isArray(list) ? list.length : 0
}

// The tile's status line. permission: omamobile-gnss's Location switch
// (enabled) and receiver (running); usage: parse() of `omamobile-location
// status`, or null when the observer is not answering. Off is always Off.
// In use only for a known active client or GeoClue's own InUse; a running
// receiver the observer cannot vouch for reads "Receiver on", never "In use".
function tileStatus(s) {
  if (!s.available) return "No GNSS"
  if (s.busy) return s.enabled ? "Turning off…" : "Turning on…"
  if (s.failed) return "Failed"
  if (!s.enabled) return "Off"
  var usage = s.usage
  if (usage && (count(usage.active) > 0 || usage.manager_in_use === true))
    return "In use"
  if (s.running && (!usage || usage.coverage !== "full")) return "Receiver on"
  return "On"
}

function pad(n) { return n < 10 ? "0" + n : String(n) }

function clock(date, twelveHour) {
  var h = date.getHours()
  if (!twelveHour) return pad(h) + ":" + pad(date.getMinutes())
  return (h % 12 === 0 ? 12 : h % 12) + ":" + pad(date.getMinutes()) + (h < 12 ? " AM" : " PM")
}

// "14:02" today, "28 Oct 14:02" otherwise. now is a Date, for the tests.
function when(seconds, twelveHour, now) {
  var date = new Date(seconds * 1000)
  var today = now || new Date()
  var sameDay = date.getFullYear() === today.getFullYear() && date.getMonth() === today.getMonth() &&
    date.getDate() === today.getDate()
  return (sameDay ? "" : date.getDate() + " " + MONTHS[date.getMonth()] + " ") + clock(date, twelveHour)
}

function duration(seconds) {
  var s = Math.max(0, Math.round(seconds))
  if (s < 60) return s + " s"
  var m = Math.floor(s / 60)
  if (m < 60) return m + " min"
  var h = Math.floor(m / 60)
  return h + " h" + (m % 60 ? " " + (m % 60) + " min" : "")
}

// The app's own name for itself (a desktop id): a label, not proof of identity.
function title(entry) {
  if (entry.app) return entry.app
  if (entry.process) return entry.process
  return "Unknown app"
}

function processLine(entry) {
  if (!entry.process) return "Process not identified"
  return entry.process + (entry.pid ? " (PID " + entry.pid + ")" : "")
}

function timing(entry, twelveHour, now) {
  var start = when(entry.started, twelveHour, now)
  if (entry.active) return "In use since " + start
  var label = END_LABELS[entry.end_reason] || "Ended"
  if (entry.ended === null || entry.ended === undefined) return start + " · " + label
  return start + " · " + duration(entry.ended - entry.started) + " · " + label
}

// What the panel says about the observer itself: honest about gaps.
function coverage(data, twelveHour, now) {
  if (!data) return "History is unavailable: the location monitor is not answering."
  var line = "Monitoring since " + when(data.coverage_since, twelveHour, now) + "."
  if (data.coverage !== "full") line += " " + (data.coverage_note || "Earlier uses may be missing.")
  if (data.history_error) line += " History could not be saved."
  return line
}

function finished(entries) {
  var n = 0
  for (var i = 0; i < count(entries); i++) if (!entries[i].active) n++
  return n
}
