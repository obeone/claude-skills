# Gotcha: Platform differences

### Action is unavailable on the target platform

**Symptom**: Shortcut imports but fails at a specific action with
"This action is not available on this device."

**Cause**: Many actions are platform-specific. Build-time, the
Shortcuts editor hides unavailable actions per device; runtime, a
cross-imported shortcut hits the wall at execution.

**Fix**: Know the availability matrix.

### macOS-only actions

These fail on iOS / iPadOS / watchOS:

| Action                                 | Identifier                               |
| -------------------------------------- | ---------------------------------------- |
| Run Shell Script                       | ⚠ `is.workflow.actions.runshellscript`   |
| Run AppleScript                        | ⚠ `is.workflow.actions.runapplescript`   |
| Run JavaScript for Automation (JXA)    | ⚠ `is.workflow.actions.runjavascriptforautomation` |
| Run Script over SSH                    | `is.workflow.actions.runsshscript`       |
| Quit App                               | ⚠ unverified                              |
| Move / Copy File (with Finder paths)   | Works with macOS-style paths only        |
| Window management actions              | macOS-only                                |
| Menu Bar (as shortcut context)         | `WFWorkflowTypes` value `MenuBar`         |
| Print Default                          | Behavior differs; macOS routes to system |

### iOS-only actions

These fail on macOS / watchOS:

| Action                            | Notes                                    |
| --------------------------------- | ---------------------------------------- |
| Take Photo                        | Camera access                            |
| Scan QR/Barcode                   | Camera access                            |
| Vibrate Device                    | Haptic engine                            |
| Flashlight                        | Camera flash                             |
| Set Wi-Fi / Cellular / Bluetooth  | iOS system controls                      |
| Set Airplane Mode                 | iOS-specific                             |
| Set Low Power Mode                | iOS only                                 |
| HomeKit scene execution           | iOS-primary; macOS support spotty        |
| Health Sample actions             | iOS + watchOS                            |
| Siri Shortcut suggestions         | iOS-specific hooks                       |
| Reading List (iOS-specific path)  | Different on macOS                       |

### watchOS-specific constraints

- No UI-blocking actions. Ask for Input, Choose from Menu show a
  limited UI; Choose from List does not support many items.
- No `Show Result`, no Quick Look.
- `WFWorkflowTypes` must include `Watch` or `WatchKit`.
- Network requests limited to ~60s (iOS limit) but effectively
  shorter in practice.

### Cross-platform design

For shortcuts targeting both iOS and macOS:

1. **Avoid platform-exclusive actions** unless guarded by an
   `is.workflow.actions.conditional` + `Get Device Details →
   System Version` / platform check.
2. **`Get Device Details`** does not expose platform name
   directly. Workaround: check presence of a macOS-only path
   (`/Users`) or use `Run Shell Script` wrapped in a try-pattern.
   ⚠ unverified clean native check.
3. **Test on both platforms before shipping.**

### Paths differ between iOS and macOS

**Symptom**: Save File works on iOS at `Shortcuts/output.txt` but
fails on macOS, or vice versa.

**Cause**: Shortcuts folders live in different locations:

- iOS: `iCloud Drive/Shortcuts/`.
- macOS: `~/Shortcuts/` (local) or `iCloud Drive/Shortcuts/`
  (iCloud-backed).

**Fix**: Use `WFFileDestinationPath` relative to Shortcuts's
default root; let the OS resolve. Avoid absolute paths.

### File URLs differ

**Symptom**: A file URL (`file://...`) produced by a macOS shortcut
doesn't resolve on iOS.

**Cause**: iOS sandbox paths differ per-app.

**Fix**: Pass files as content items, not URLs, when chaining
between platforms.

### watchOS — Run Shortcut from watch calls the iPhone

When a shortcut is triggered from Apple Watch, it may execute on
the paired iPhone (not the watch) depending on the action set. No
programmatic control; Shortcuts decides per-action.

### visionOS

visionOS 1+ supports Shortcuts as a subset of iOS actions. Most
action identifiers carry over; window / environment-specific
actions may be exposed via new App Intents. ⚠ Full matrix
unverified.

### HomeKit actions degrade on non-home-hub contexts

**Symptom**: Home automation fires a shortcut that includes a
HomeKit scene action; the scene doesn't run.

**Cause**: Some Home actions require a hub (Apple TV / HomePod /
iPad). Remote execution without a reachable hub fails silently.

**Fix**: Ensure the home has a hub; guard remote actions with
network reachability checks.

### App availability affects import, not just run

**Symptom**: Shortcut imports fine but an action shows "Get this
app" at the action tile.

**Cause**: Third-party action from an uninstalled app. Shortcuts
doesn't block import; it gates at run time.

**Fix**: List dependencies in your documentation. Check via
`validate-shortcut.py` — it warns for unknown third-party
identifiers.
