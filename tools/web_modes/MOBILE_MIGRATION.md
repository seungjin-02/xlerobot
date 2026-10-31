# Mobile shared-backend implementation

## Current snapshot (2026-10-31)

The latest source restores the original dark mobile UI, click-to-toggle driving,
three simultaneous camera panes, spaced map controls, map management, native
mission workflows and inline PIN errors. Run `python tools/preview_ui.py` for a
read-only local preview at http://127.0.0.1:18090/. No robot is required.

Robot release r5 was deployed while stationary on 2026-10-30. The subsequent
three-camera/layout changes are local and have NOT been deployed to the robot.
Physical camera reception and autonomous movement remain unverified; USB device
faults were unresolved at the last connected inspection. GitHub merge does not
constitute a device deployment or physical validation.

The sections below are a chronological implementation log; earlier local-only
and r3/r4 statements describe those stages, not the latest release.

## Initial implementation

The new entry point is `app/mobile_gateway.py --config <existing-private-config>`.
It serves mobile assets and forwards allowlisted requests and authenticated WebSocket
connections to the native operator on loopback port 8080. It does not instantiate
RosBackend or launch a driver. The existing service configuration is unchanged;
this entry point has NOT been deployed or enabled.

Native reuse: `app/mobile/native/{connection.js,format.js,widgets/map_view.js,widgets/canvas.js}`
are copies of the installed `/home/roboseasy/lekiwi_web_operator/web/js/` sources
retrieved read-only on 2026-10-30. Keep upstream attribution/license review as a
release gate; these are local integration sources, not separately published code.

Implemented locally: PIN login; client identity tied to authenticated session;
allowlisted native APIs; WebSocket relay; native live speed levels; hold-to-drive;
map list/preview/save and mapping process controls; map/scan/path display; native
navigation goal/initial pose/speed; system status and logs.

Remaining: mission orchestration (return, route, exploration), persistent routes,
map management/export beyond listing/save, mobile browser QA, complete gateway
integration tests with actual native WS message streams, correct trolley geometry
in native planner/exploration, exclusive service migration and rollback, idle
robot deployment verification. New mission modes stay unavailable until integrated.
Old map and recording directories have not been modified.

Validation: Python compile, mobile JS syntax, six gateway tests (WS welcome,
PIN, identity isolation, route allowlist, unavailable upstream), five speed tests.
Windows import of server requires Linux fcntl: run gateway suite in WSL Ubuntu24.04.
No motor, arm, mapping, exploration or navigation command has been sent to hardware.
USB over-current and absent device aliases remain a separate physical blocker.
## Additional local progress

`mobile/mission.js` now sequences goal, visit-and-return, and repeated route missions.
It requires active-goal observation and position-consistent success before advancing.
Timeout return cancels the current goal and waits for a terminal acknowledgement.
Disconnect invalidates in-flight async submissions; manual directional controls are
blocked during mission ownership. Six Node tests cover these transitions.

Playwright CLI tested the real local gateway login at 390x844. The map tab has
scrollWidth 390 at viewport width 390; map canvases mount. Native engine was not
running in that test, so WebSocket failures were expected; no end-to-end native
mission execution is implied. Initial browser console showed only expected
unauthenticated status 401, favicon 404 and unavailable native WebSocket messages.
Map display uses the confirmed trolley's conservative 0.30m radius; this is a
visual change only, not evidence that native planner geometry has been migrated.

Still incomplete: persistent saved routes, exploration+return, map export/management,
whole-flow backend integration, browser QA with native/mocked live frames, native
geometry migration, mode services migration, deployment and idle verification.
## Map library, exploration workflow and shared service staging

- MapLibrary stores labels and up to 100 finite waypoints per map in a separate
  atomic metadata file. Original map files and recordings are untouched.
- ZIP export contains sanitized YAML, its local image, optional local pbstream,
  and mobile route metadata. Traversal/external symlinks are rejected.
- ExplorationMission stages native exploration stop, map save confirmation,
  mapping stop, native navigation startup, initial pose, localization and home goal.
  It stops progression on failed/unconfirmed stages. Four mocked workflow tests
  pass; these do not validate native process timing or real navigation.
- Shared mode helper behavior is gated by root-owned state/shared-native marker.
  With the marker, factory engine plus mobile frontend are one custom mode;
  legacy camera/LiDAR services still count as conflicts. Marker is NOT installed.
  21 switcher tests pass, including five shared-engine cases.
- Six map-library tests pass in WSL, including unchanged source map, persistence,
  export contents, nonfinite route and path/symlink rejection.

Remaining release gates include native geometry/profile migration, end-to-end
native WS/API contract tests, UI review of new controls, service migration and
rollback packaging, stationary deployment verification. No production service
or map data has been changed by these local additions.

## Production state after r3 deployment (2026-10-30)

Shared-native release `/home/roboseasy/xlerobot-mobile-releases/mobile-20261030-r3`
is active. Root marker installed. Original files are backed up in
`/home/roboseasy/xlerobot-web-migration-20261030/shared-native-backup-r3`.
Earlier local-only notes above describe historical stages.

Runtime verification: PIN login and authenticated HTTP status/maps succeeded;
WebSocket relay returned native welcome and status. All hardware processes are
stopped; no holder, powered_by_us=false, motor readiness unknown. USB device
aliases all absent. Engine uses ROS domain 41 as configured by the original service.
Native speed policy currently exposes 0.10m/s fallback, not 0.23m/s hardware-derived
limits, because the base is not available. No hardware launch or movement was tested.

Native exploration collision radius set to .30m (rotation .38m including existing
.08m margin); both native costmaps use .30m radius/.45m inflation. Visual radius is
.30m. These are conservative configuration changes, not physical validation.

Release fixes: LF normalization for executable shebang; readiness check no longer
repeatedly authenticates while waiting for native observer startup. First two
failed attempts rolled back and left robot services stopped before r3 succeeded.

Still required before completion: authenticated browser runtime QA, full mode
switch roundtrip with shared architecture, post-deployment configuration/data
checks, clear missing-device feedback, and final review of native API contracts.

## Final audit (2026-10-30)

The final deployed release is r4, with native camera stream selection and readable
system/USB diagnostics. Missing USB motor/LiDAR blocks starting operations at both
UI and gateway. Earlier remaining-release-gate notes are historical: actual shared
mode roundtrip, authenticated mobile browser QA, final served-asset comparison and
stationary deployment audit have now passed. Python 257 + Node 10 tests passed.
See outputs/xlerobot-trolley-20261030/제어센터-개편-배포결과.md and final audit JSON.

Physical motion and camera/sensor reception remain unverified because USB devices
are absent. This software/stationary completion does not assert working physical
autonomy. The configured data roots contain no files on this new robot. No old
robot data was migrated or deleted. No motor/arm movement test was performed.
