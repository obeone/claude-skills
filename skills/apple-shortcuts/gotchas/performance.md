# Gotcha: Performance

### Shortcut times out mid-execution

**Symptom**: Shortcut runs for 30+ seconds and terminates with
"Timed out".

**Cause**: Shortcuts app extensions have a background time limit
(~30–60s on iOS, longer on macOS). Long Get Contents of URL calls
or heavy loops hit the wall.

**Fix**:

- Break the shortcut into smaller pieces chained via
  `Run Shortcut`.
- Move heavy work to Scriptable (longer runtime) or a server.
- Cache results in Data Jar to avoid re-fetching.
- Reduce `Repeat` count or use server-side batching.

### Repeat over large list is slow

**Symptom**: `Repeat with Each` over a 1000-item list takes
minutes.

**Cause**: Each iteration spins up the action pipeline. Per-item
overhead is high.

**Fix**:

- Do batch operations server-side when possible.
- If client-side is required, use Scriptable for a tight JS loop
  and return the transformed list.
- Use Toolbox Pro's bulk actions (Sort Files, Filter Files) when
  they apply.

### Get Contents of URL returns partial data for large responses

**Symptom**: Responses > 50MB truncate or the shortcut crashes.

**Cause**: Extension memory limit on iOS (~120MB for extensions in
recent iOS; less in practice).

**Fix**:

- Request compressed responses (`Accept-Encoding: gzip`) — reduces
  wire size, Shortcuts auto-decompresses.
- Use pagination.
- Download to file via Actions app's Download File, process
  streaming.

### Show Result on large data blocks the shortcut

**Symptom**: Show Result with a large dictionary takes several
seconds to render, freezes the UI.

**Cause**: The modal renders the entire data model.

**Fix**: Use Quick Look (`is.workflow.actions.viewresult`) for
large data, or summarize before Show Result.

### Shortcut fails after importing when called by another shortcut

**Symptom**: A newly-imported shortcut works manually but not when
called by another.

**Cause**: iCloud sync latency — the called shortcut's index is
stale.

**Fix**: Wait 30–60s for the device's local Shortcuts index to
rebuild. Or open Shortcuts.app once to force a refresh.

### Personal automation doesn't run when device is locked

**Symptom**: Time-based automation at 07:00 runs late or not at all.

**Cause**: Some triggers require device wake state. Also, iOS can
delay background tasks to conserve battery.

**Fix**:

- For reliable scheduled execution, use Pushcut's server-side
  scheduling.
- For time-critical workflows, use an Alarm trigger (alarms wake
  the device) rather than Time of Day (which doesn't always).

### Nested Run Shortcut calls stack-overflow

**Symptom**: "Too many nested shortcut calls."

**Cause**: Call depth limit (~10 as observed).

**Fix**: Flatten the call graph. Use Data Jar to pass intermediate
state if deep chains are required.

### watchOS shortcuts fail on complex logic

**Symptom**: Shortcut runs on iPhone but fails on Apple Watch.

**Cause**: Watch has tighter time, memory, and UI limits. Some
actions silently fall back to the paired iPhone.

**Fix**: Design watch shortcuts to be simple and short. Test on
the watch; don't assume iPhone behavior transfers.

### Repeated Get Contents of URL to the same host rate-limits

**Symptom**: After a few hundred rapid calls, requests fail with
HTTP 429 or hang.

**Cause**: Client-side rate limiting is non-existent in Shortcuts
— it's on the server.

**Fix**: Insert `Wait` actions between calls. For batch fetches,
respect the server's documented rate limit; add an exponential
backoff via `Repeat` + `If status is 429`.

### Large dictionaries slow down Get Dictionary Value

**Symptom**: Dict with thousands of keys → Get Dictionary Value
takes seconds per access.

**Cause**: Linear scan per access.

**Fix**: Partition data into smaller dicts. Or process with
Scriptable / Jayson which have better JSON performance.

### Parsing HTML with native actions is unreliable

**Symptom**: Get Contents of Web Page + text extraction produces
garbled output.

**Cause**: HTML parsing is minimal natively.

**Fix**: Use Run JavaScript on Web Page (Safari only) for clean
DOM access. Or fetch the raw HTML and pass to Scriptable for
proper parsing.

### Shortcuts cache doesn't invalidate after action updates

**Symptom**: Third-party app released a bug-fix update; old
shortcut still shows old behavior.

**Cause**: Shortcut's action metadata is cached at import time.

**Fix**: Re-import the shortcut after the app update, or edit
trivially in Shortcuts.app to force a refresh.

### Run JavaScript on Web Page times out at 10s

**Symptom**: Complex JS returns "Script timed out."

**Cause**: Safari-extension time budget.

**Fix**: Make the JS fast (< 2s). For longer work, fetch the page
via Get Contents of URL and process with Scriptable.
