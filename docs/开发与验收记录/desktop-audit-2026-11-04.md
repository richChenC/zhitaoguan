# Desktop regression checkpoint

This is a source-level regression checkpoint, not a packaged release acceptance.

## Runtime fixes

- Opening a chart in a native comparison window now opens enclosing `details`
  elements. The position distribution chart no longer remains hidden behind a
  collapsed explanatory section.
- Plate, tube trend and distribution headings reserve adequate space for their
  action buttons. Scope captions wrap without intersecting those buttons.
- Dark mode command captions and visualization methodology summaries have
  improved contrast.

## Regression repairs

- Ledger editing explicitly switches to all columns before editing secondary fields.
- Original-record verification checks all 19 fields, including statistical
  conclusion and classification basis.
- Settings tests check visible tube halves. Unselected channels remain white;
  they are not assumed to be NDD.
- Real-data 3D verification explicitly selects scoped records before expecting
  defect overlays.
- Position reconciliation uses the local source containing its five known
  instrument-label examples. Both database sources are copied read-only.
- Plate layout verification now rejects caption/action intersections.

## Verified evidence

All paths below are under `G:\thimble-audit-20261104`.

| Evidence directory | Result |
| --- | --- |
| `2026-11-03T17-35-12-572Z` | 15 passed; five failures investigated and subsequently retested |
| `2026-11-03T17-50-00-038Z` | Plate scope, all native chart windows and workspace usability passed |
| `2026-11-03T17-51-40-735Z` | Model controls, scope/plate, double click, position reconciliation and RPT folder regression passed; real-data test later repaired |
| `2026-11-03T17-59-19-043Z` | Real-data 3D and cross-window settings linkage both passed |
| `2026-11-03T18-02-24-654Z` | Native chart windows passed; added geometry assertion exposed narrow heading overlap |
| `2026-11-03T18-03-42-365Z` | Plate scope passed after heading repair, including light/dark geometry checks |

The last plate run includes 800, 1000 and 1440 pixel layouts, export checks,
50-channel behavior, historical replacement scope, empty states and failed
reload recovery. The final dark 800 pixel screenshot was visually reviewed.

Source audit: 354 files, zero errors. `git diff --check` and syntax checks for
modified test/runner modules passed. The earlier full Python run reported
392 passing tests; it was not repeated after these UI/test-only changes.

## Limits

- This checkpoint does not claim exhaustive coverage of every possible operation.
- No installer or portable package was rebuilt in this continuation.
- Existing release packages do not include these latest source changes.
- Tests use isolated database copies and verify unchanged source hashes where
  supported; no deliberate writes to formal databases were performed.
- The initial run exhausted D: space. Its generated evidence was moved to
  `G:\thimble-audit-20261104-evidence`; later runs all used G:.

## Follow-up regression checkpoint

- Complete desktop suite: **42 passed, zero failed**.
  Evidence: `G:\thimble-audit-20261104-full-desktop\2026-11-03T21-39-24-879Z\results.json`.
- Full Python unittest discovery completed with exit code zero in this
  continuation. Its console output was not persisted as a separate log.
- `npm run check` passed, including 103 ESM files and authentication syntax.
- Selected NDD records now paint the relevant tube half gray; unselected
  channels remain white. Import outcome regression verifies selection and
  deselection through the record checkbox.
- Workspace refinement now seeds blank NDD, slash and measurable WAR examples
  exclusively in its copied test database. It no longer assumes the formal
  source contains a specific N109/42 record or a measurable scatter point.
- Cross-window review refresh and concise all-scope export naming remain
  covered by the desktop/backend regressions.

These results validate the current source version. Newly built installer and
portable artifacts, their clean startup, and a new formal database integrity
checkpoint remain outside this completed test batch.

## Packaged startup follow-up

New backend, NSIS installer and portable launcher were built under
`G:\thimble-release-20261104`, preserving previous release artifacts.
Clean packaged and independently installed applications passed setup, settings,
report catalog, nonblank model and shutdown checks; both matched 162 UI assets
against current source hashes. Actual portable extraction/startup also passed
with exit code zero and backend shutdown verified.

Read-only integrity checks returned `ok` for both database sources:
4517 findings in the development source and 5183 in the user runtime source.
See `G:\thimble-release-20261104\验收记录.md` for evidence paths and limits.
Full packaged business regression, historical backup checks and complete
hardware/DPI coverage remain unverified.

## Revised package verification

The r2 package includes the neutral-gray NDD summary fix in both themes.
Actual portable launch and independent installer execution passed. The installed
application passed clean startup with 162 asset hashes, lifecycle/report export,
state maintenance, settings linkage, visualization reconciliation, local roles
and backup/restore/session invalidation checks.

Evidence: `G:\thimble-release-20261104-r2\验收记录.md`.
The complete 42-test desktop group has not all been run against this installed
executable; the report explicitly preserves that limitation.

Four more installed UI suites passed: notifications, native chart windows,
control alignment/scaling, and visualization collapse/selection controls.
Evidence: `G:\thimble-release-20261104-r2\installed-ui\2026-11-03T22-29-22-669Z`.
The release runner now rejects unsupported packaged jobs before launching any
tests and records the runtime/executable in results. Its local-account alias
and refusal path were verified separately under the r2 runner-validation folder.

Installed status comparison and cross-group refresh checks passed under
`G:\thimble-release-20261104-r2\refresh-verification`.
The cross-group suite is now included in the standard desktop job list.
Source review also found misleading import rollback guidance claiming that tube
states were preserved. Both diagnostic and confirmation copy now explain the
associated state rollback and conflict cancellation. Source import-recovery and
cross-group tests passed under the r2 rollback-guidance directory, including
canceling confirmation without changing imported records.
The r2 binaries predate this last guidance correction and need rebuilding.

## Deletion and Recycle Bin Follow-up

Corrected deletion preview counts to match the tables actually changed by each
scope. Single-tube history deletion now requires and enforces a site; unit
deletion enforces both site and unit, including when inconsistent records share
an outage code. Purging a batch removes its deleted findings, tube states and
import batches, and reports the actual combined count.

Removed unsupported deletion switches from the desktop confirmation. The
service always backs up and moves data into the recycle bin; the dialog now
states that policy and reserves permanent deletion for the recycle bin.
Site/unit/all labels describe detection-record deletion rather than suggesting
that unrelated application data is cleared.

Evidence:
- 403 Python tests passed in the complete discovery run.
- Four focused deletion tests passed after the final unit-scope correction.
- Notification interaction and dark-dialog suites passed on source Electron.
- JavaScript/ESM checks, the 355-file source audit and `git diff --check` passed.
- Logs: `G:\thimble-audit-20261104-delete-check`.

The complete Python run started before the last unit-scope refinement; the four
focused tests cover that final backend change. The final paragraph-spacing
change passed the repeated dark-dialog suite under
`G:\thimble-audit-20261104-delete-final`; the deletion screenshot was also
visually inspected. These fixes are source changes and are
not included in the existing r2 installer or portable executable.

## Mutation Refresh Regression

A new desktop interaction test reproduced a stale workbench after deletion:
the service had removed the finding while the displayed row and selection
remained. Deletion and restore events now reload the workbench overview and
ledger, clear stale selection and reset pagination. Removed the redundant
generic-change forwarding from the deletion toolbar; charts and reports already
subscribe to the specific mutation events.

`tests/deletion_refresh_desktop.mjs` verifies failed deletion/retry, actual
source removal, cached chart coverage changing from 3/50 to 2/50, recycle restore,
and removal/restoration of the exact source ID in an already-open report.
The test uses an isolated synthetic database and is now part of the desktop
release suite, with explicit packaged-executable support.

Source status-change, cross-group and deletion-refresh suites all passed:
`G:\thimble-audit-20261104-refresh\2026-11-03T23-02-36-384Z`.
The failing baseline is retained under
`G:\thimble-audit-20261104-refresh-baseline`.

The same test additionally passed deletion of the final records and recovery
from a completely empty database. It verifies that cached charts clear their
coverage, report previews clear and report export becomes unavailable:
`G:\thimble-audit-20261104-refresh-empty`.

The unit group exposed a separate static-chart rendering regression:
`tooltip:false` still queried the DOM when attaching disabled tooltips.
Disabled tooltips now return after listener cleanup, before DOM access.
The existing model verification exercises this static-rendering contract.

Visual inspection also exposed an obsolete undo action after recovery through
the recycle bin. Restore responses now include their batch ID, actual affected
row count and an already-restored flag. Restore and purge serialize their
read/write transactions; repeated restore reports zero new changes without
duplicating the restore audit, and restored history cannot be purged as a
deleted batch. The desktop retires the matching obsolete undo action.
Focused coverage also checks rollback if writing the restore audit fails.

## R3 Validation

The final backend changes passed all 406 Python tests. The eleven unit/source
jobs passed after the static-chart correction. Syntax checks passed for 104
ESM files; the source audit covered 356 files with no errors.

Twelve installed-application suites passed across the r3 installed-regression
and installed-followup evidence directories. The runtime-database status test
required a dedicated administrator in its isolated copy; existing original
accounts were preserved. The portable startup test now waits for completion
of account-status loading before asserting setup mode.

The last notification-only adjustment removes the obsolete undo notice when a
batch is restored from the recycle bin, preventing duplicate success messages.
The final installer was rebuilt and reinstalled. Clean startup, 162 asset
hashes, nonblank 3D rendering and the two affected desktop suites passed again.
Full evidence and verification limits are recorded in
`G:\thimble-release-20261104-r3\验收记录.md`.

## Native Export Failure Handling

Native PNG and report-header saves previously wrote directly to the final path,
which could truncate an existing file on partial write failure. A shared desktop
helper now writes an exclusive temporary file in the destination directory and
renames it after completion. Failure preserves the previous target and reports
actionable disk-full, permission/lock or missing-directory guidance.

Native export audit registration now follows successful saving, after permission
is rechecked. If audit registration fails after the real file was saved, a native
warning distinguishes those outcomes and says that re-export is unnecessary.
Canceled and failed writes do not create successful-export records.

Four focused file-save tests and the native Electron export suite cover partial
disk-full writes, locked targets, canceled dialogs, retry, matching saved bytes
and audit hashes, audit failure after saving, and the actual report-header button.
The existing selection/PNG-export desktop suite also passed.
Evidence: `G:\thimble-audit-20261104-native-export-final\2026-11-03T23-46-57-364Z`.
Both new suites are registered in the release runner. The desktop suite now has
45 jobs; the unit/source group has 12 jobs.

These export changes postdate the r3 binaries. They are verified source changes;
the existing r3 package remains usable but does not contain them. A future
consolidated rebuild and packaged regression must include these changes.

## State Save Versus Refresh Feedback

State-list loading now returns an explicit success/failure result while retaining
its inline retry control. Single-tube saves and inline saves distinguish a
committed database change from failure to reload the list. The warning explicitly
says not to repeat saving; reloading updates the selected form's stored version.
Save result text is applied after the busy-state redraw, which previously
cleared both success and failure instructions.

Batch import and lifecycle mutation notifications now fire immediately after
the service confirms saving, before UI reload. Thus list-load failure does not
prevent other charts/reports from receiving the mutation notification.
Batch import feedback preserves the committed count and distinguishes a failed
list refresh from an import failure.

The added maintenance scenario injects HTTP 503 for the state-list request
after a real successful save, checks the committed note directly, clicks reload,
then edits/saves the same tube again successfully. State-maintenance,
state-batch and status-change desktop suites passed under
`G:\thimble-audit-20261104-state-refresh-final\2026-11-03T23-59-10-448Z`.
The first failed regression, which exposed result text being cleared on redraw,
is retained under `G:\thimble-audit-20261104-state-refresh`.
These changes postdate the r3 packages and require consolidated packaged
verification along with the native-export fixes.

## UI and Boundary Follow-up

Five source Electron suites passed against the export/state-refresh changes:
workspace edge cases, workspace refinement, report draft, report layout and
professional UI. Evidence:
`G:\thimble-audit-20261104-ui-edge-followup\2026-11-04T00-03-02-030Z`.

Coverage includes incomplete/partially quantified records, small numeric
changes, stale scope rejection, raw-record paging failures/timeouts/cancellation,
source drilldown, overlapping chart points, keyboard scope selection, configured
NDD colors, Word/Excel exports and maintenance control alignment.
Report-preview layouts were measured at 1920, 1366, 1280, 820 and 390 pixels.
The 800-pixel dark-workbench and 390-pixel report-preview screenshots were
visually inspected. The report retains a scrollable full-page preview rather
than shrinking document text to unreadable sizes.

Visual inspection found inconsistent channel terminology in the workbench:
the input placeholder and no-match guidance still said "套管编号" while the label
and table used "通道编号". Both user-facing strings now use "通道编号".
This final text-only change is additional to the five passing suites.
The r3 packages remain unchanged and do not include these source follow-ups.

## Import and Restore Result Follow-up

Excel import previously replaced a successful committed batch result with
"processing failed" if the subsequent workspace refresh threw. The result now
keeps its actual inserted/skipped counts and file details, adds an inline
refresh warning, and explicitly asks users not to repeat import. The warning
uses separate light/dark colors and records a notification without a floating
toast covering the open import dialog.

The outcome regression imports a real NDD workbook into an isolated database,
injects HTTP 503 for overview refresh, verifies the inserted record count, and
then removes the failure and verifies the imported channel appears in the
workbench. The first run exposed an incorrect test assumption equating raw
database totals with filtered workbench totals; the assertion now checks the
actual imported channel instead.

Restore had a related feedback issue: a post-restore refresh exception wrote
its error into the already closed confirmation dialog. A visible warning now
states that restoration succeeded and refresh failed, without suggesting a
second restore. The settings regression simulates the committed restore
response and a refresh exception; it does not perform a restore on formal data.

Passing evidence:
- Import progress, recovery and RPT folder regression:
  `G:\thimble-audit-20261104-import-refresh\2026-11-04T00-13-00-766Z`
  (the initial import-outcome test failed at the incorrect final assertion).
- Corrected import outcome and native Electron settings workspace:
  `G:\thimble-audit-20261104-import-refresh-final\2026-11-04T00-15-37-035Z`.
  Settings covers persistence, backup confirmation, restart, native window
  sizing and 100/125/150 percent display scaling.

RPT folder screenshot output now honors the configured G-drive evidence root.
The import outcome suite uses headless Edge with the local Python service;
the settings suite uses source Electron. These source changes are not yet in
the r3 installation or portable packages.

Final inline-warning layout and source audit passed:
`G:\thimble-audit-20261104-import-layout-final\2026-11-04T00-17-21-280Z`.
Visual review at 390 pixels in dark mode then identified pale queue action
buttons. Scoped dark styles now cover their normal and disabled states.
The final import-outcome regression, including dark button surface and warning
overflow checks, passed:
`G:\thimble-audit-20261104-import-dark-final\2026-11-04T00-18-53-352Z`.
The final narrow dark screenshot was visually inspected; syntax and
`git diff --check` also passed.

## State, Settings and Audit Synchronization

The 406-test Python suite and five source Electron suites passed:
status changes, independent visualization windows, settings linkage,
visualization accuracy and deletion/restore freshness. Evidence:
`G:\thimble-audit-20261104-data-linkage\2026-11-04T00-20-33-775Z`.

Import audit mutations previously refreshed the audit list before broadcasting
the committed change, and overwrote a failed list-read message with an
unqualified success message. Review, rollback and restore now publish committed
changes first, distinguish list-refresh failures from failed mutations, and
disable stale mutation controls until a successful refresh. Review success says
that downstream refresh was requested rather than claiming every consumer has
already completed it.

The extended cross-group Electron test injects HTTP 503 for audit-list reads
after actual review, batch rollback and batch restoration. It verifies correct
committed feedback, disabled stale controls, recovered controls after refresh,
main-ledger counts, report refresh, source preservation and cleared selection.
Evidence:
`G:\thimble-audit-20261104-audit-refresh\2026-11-04T00-25-24-426Z`.
All test data is isolated on G; formal databases were not written.

## r4 Consolidated Package Verification

The accumulated source fixes are now included in installation and portable
packages under `G:\thimble-release-20261104-r4\packages`. Previous release
directories were retained. Installation into the independent r4 directory
returned exit code 0.

Clean installed startup passed with 162 UI asset hashes matching current
source, local administrator creation, empty isolated database, correct settings
placement and nonblank 3D rendering:
`G:\thimble-release-20261104-r4\installed-clean\packaged-clean-1793752384408`.

Seven installed suites passed: settings workspace/scaling, state maintenance,
notification interaction, settings linkage, visualization accuracy, cross-group
audit (including committed mutations with failed refresh) and native export
failure protection:
`G:\thimble-release-20261104-r4\installed-regression\2026-11-04T00-33-31-630Z`.
Settings-workspace now explicitly supports packaged execution and asserts
`app.isPackaged`; the runner allowlist includes that verified path.

Actual portable extraction/startup/admin setup/3D/shutdown passed with exit
code 0:
`G:\thimble-release-20261104-r4\portable-delivery\portable-launch-1793752494314`.
Package hashes are in the r4 `package-sha256.json`; concise Chinese acceptance
notes are in `验收记录.md`. The packages are unsigned.

The complete 45-suite desktop matrix has not been rerun on r4; the seven
installed suites above are the current package-specific evidence.
Read-only integrity checks still report `ok`, 4517 development findings and
5183 runtime findings. Final syntax checks and `git diff --check` passed.

## Export Scope and Wider Workflow Follow-up

Nine source desktop suites passed: release lifecycle, selected-image export,
unified ledger, import progress/outcomes/wizard, local accounts/permissions,
report draft and report layout:
`G:\thimble-audit-20261104-report-permissions\2026-11-04T00-38-32-874Z`.

Review found that ledger export applied analyst, tube, measurement-channel and
data-group filters to its records but omitted those conditions from the
summary scope and filename. An analyst-only export could therefore say
"all records". Ledger summaries now list all seven supported scope fields;
filenames identify selected fields within the existing bounded naming format.
Export audit metadata includes analyst/tube/channel/group as well.
The summary separately explains that state-event rows follow site/unit/outage/
tube filters, because those events do not have analyst or acquisition-group
ownership. Scope and explanatory rows are merged across the summary width,
wrapped and assigned sufficient height.

Thirteen ledger tests and five visual-summary tests passed after the change.
The added test verifies real filtered workbooks, record counts, filename scope,
summary text and wrapping. Source audit and actual Electron ledger export also
passed:
`G:\thimble-audit-20261104-ledger-scope-final\2026-11-04T00-43-00-615Z`.
These export-scope changes postdate r4 and are not included in its packages.

Eight further source desktop suites passed:
window sizing, night-mode workspace, night-mode dialogs, plate scope,
workspace usability, control alignment, information hierarchy and visualization
controls. Evidence:
`G:\thimble-audit-20261104-ui-matrix\2026-11-04T00-43-21-474Z`.
Window sizing covers 13 native size/zoom combinations (800 through 1920 pixels,
including 125/150 percent scaling), model canvas pixels and scope/tool overlap,
all 50 tube positions and fullscreen restore. Visualization controls verify
real collapse height changes, tab/refresh persistence and light/dark behavior.
Usability checks verify scoped raw-record drilldown and the 50-channel change
matrix. The 800x600 at 150-percent state screen and desktop dark change-matrix
screenshots were visually inspected.

## Delayed Note Recognition and Model Follow-up

Twelve source desktop suites passed: service isolation, settings window,
workbench display, large state import, visualization analysis/history/workspace,
reference model, real-data model, scope/plate linkage, double-click linkage and
position resolution:
`G:\thimble-audit-20261104-model-history\2026-11-04T00-49-51-758Z`.

Inspection found that a delayed maintenance-note recognition response could
overwrite the editor after the user changed its note or selected another tube.
The recognition action now captures the edit revision and form values, checks
them before opening preview and again before applying the result, and discards
obsolete results with a message that current input was preserved.

The maintenance Electron suite now holds a real recognition response, edits the
note or selects tube 11 instead of tube 10, then releases the old response.
Both scenarios preserve the exact current form values, avoid opening an obsolete
preview, and leave recognition available for retry. The normal recognition and
save path is still tested immediately afterward. The full maintenance suite
passed:
`G:\thimble-audit-20261104-note-race\2026-11-04T00-52-29-711Z`.
This fix, like the ledger-scope follow-up, is newer than the r4 packages.

An evidence-index check found passing source results for all 45 configured
desktop jobs across the day's audit directories. This is aggregate evidence
from successive source revisions, not one full-matrix run of an immutable
current build; r4's seven installed suites remain its package-specific scope.
Source audit and batch-state regression also passed after the recognition
change:
`G:\thimble-audit-20261104-state-race-followup\2026-11-04T00-55-33-324Z`.
JavaScript syntax and `git diff --check` passed.

## Manual Outage Scope Recovery

Creating a manual outage previously closed the dialog and claimed readiness
even when the subsequent state-list read returned failure. The dialog now
retains the confirmed saved scope, explains the refresh failure and offers
"reload and use" without another POST. Scope inputs are locked after commit,
while close remains available after the failed reload. During the active
save/load, inputs and close are disabled and Escape/default submission cannot
close the dialog. Enter in the outage input invokes the add action.

Legacy-scope migration now likewise distinguishes committed scope records from
list-refresh failure rather than reporting unqualified readiness.

The Electron maintenance test creates a real F198 scope in its isolated
database, holds the successful server response to check busy/close behavior,
injects a list-read HTTP 503, retries, and verifies exactly one scope POST,
correct selected scope and no new detection records. It also tests mismatched
site/outage validation. Source audit, batch-state and maintenance suites passed:
`G:\thimble-audit-20261104-manual-scope\2026-11-04T01-00-05-067Z`.
These changes are newer than r4.

## Complete Current-Source Regression

A single sequential run of the complete configured release-check matrix passed:
58 jobs, zero failures, comprising source audit plus 11 unit/model checks,
407 Python tests and all 45 desktop jobs.
Evidence:
`G:\thimble-audit-20261104-full-current\2026-11-04T01-02-21-945Z`.

The run includes ledger scope, delayed-note recognition and manual-scope
recovery fixes. All 359 inventoried file hashes were rechecked after completion:
none changed during the run. This supersedes the earlier aggregate-only
source evidence, but does not extend r4's package-specific verification.

Final `git diff --check` passed. Read-only integrity checks returned `ok` for
both existing databases, with 4517 development and 5183 runtime findings.
The current installation/portable r4 artifacts still predate the ledger-scope,
note-recognition and manual-scope fixes; those need a consolidated package
and installed regression before delivery can be called current.

## r5 Current Package Delivery

The ledger-scope, note-recognition and manual-scope fixes are now included in
independent r5 installation/portable artifacts:
`G:\thimble-release-20261104-r5\packages`.
The backend was rebuilt from current source and installation returned code 0.

Eight installed suites passed:
`G:\thimble-release-20261104-r5\installed-regression\2026-11-04T01-33-24-602Z`.
They cover real workbook ledger import/edit/download, state maintenance,
settings linkage, local accounts/permissions, visualization accuracy,
cross-group audit, deletion/restore freshness and native export failure safety.
The ledger test now explicitly supports packaged execution and asserts
`app.isPackaged`; its runner allowlist entry is enabled. These test-only edits
postdate the complete source regression; production code did not change.

Clean installed startup passed, including 162 source-matching UI assets,
administrator creation, empty isolated database and model rendering:
`G:\thimble-release-20261104-r5\installed-clean\packaged-clean-1793756063896`.
Actual portable startup/shutdown passed with code 0:
`G:\thimble-release-20261104-r5\portable-delivery\portable-launch-1793756147862`.
Final package hashes and Chinese acceptance notes are in the r5 root.
The eight installed suites are package-specific evidence; the full 45-suite
matrix remains source-runtime evidence. The packages are unsigned.

## r5 Installed UI Follow-up

Seven additional installed suites passed without production changes:
settings workspace/scaling, release lifecycle, notifications, status changes,
independent visualization windows, control alignment and visualization
controls/collapse.
Evidence:
`G:\thimble-release-20261104-r5\installed-ui-followup\2026-11-04T01-40-33-537Z`.
The dark collapsed-panel screenshot was visually inspected: the collapsed
content releases its layout space and following charts remain visible.
Together with the earlier eight suites, 15 distinct configured desktop jobs
now have r5 installed evidence. Remaining desktop jobs retain source-runtime
evidence only. No new production edits or rebuild were made in this follow-up.

## r5 Installed Report Verification

Report-draft and report-layout tests now explicitly support packaged execution,
assert `app.isPackaged`, and are admitted by the release runner's packaged
allowlist. Both passed on the existing installed r5:
`G:\thimble-release-20261104-r5\installed-reports\2026-11-04T01-47-13-347Z`.
No production files changed.

Checks include real Word/Excel export content, draft editing/undo, source
selection, site-specific header isolation, obsolete preview rejection and
export availability. Layout covers 1920/1366/1280/820/390 widths with the draft
editor open and closed. The 390-pixel open screenshot was visually inspected;
the paper itself retains internal scrolling rather than shrinking its text.
Seventeen distinct configured desktop suites now have r5 installed evidence.
Test syntax and `git diff --check` passed.

## r5 Installed Model Verification

Three more installed suites passed: real-data model, scope/plate behavior,
and double-click linkage. Evidence:
`G:\thimble-release-20261104-r5\installed-models\2026-11-04T01-52-02-159Z`.
Checks cover 50 channels, selected-record defect placement, maintenance offsets,
historical plugged tubes, scope isolation, loading recovery and four viewports.
The source database hash stayed unchanged. The centered 800x600 model screenshot
was visually inspected. Twenty distinct installed suites now have evidence.
Only test launch support and the runner allowlist changed; no rebuild was needed.

## r5 Installed Dark-mode Verification

Both dark workspace and dark dialog suites passed:
`G:\thimble-release-20261104-r5\installed-dark-followup\2026-11-04T01-56-50-761Z`.
Workspace samples reported zero contrast failures and zero checked overflow.
Dialog checks include import, mapping errors, delete/restore, report choice,
new scopes, batch preview/saving/errors and notification levels, with zoom cases.
The zoomed batch preview screenshot was visually inspected: readable wrapping,
internal table scrolling and unobscured footer controls.
Twenty-two distinct installed suites now have evidence; remaining configured
desktop suites still have source-runtime evidence only. Test-only changes
enable packaged launches and assert `app.isPackaged`; production files unchanged.

## r5 Installed Batch Verification

State-batch and large state-import suites passed on installed r5.
Evidence:
`G:\thimble-release-20261104-r5\installed-batch-window\2026-11-04T01-59-18-091Z`.
Batch checks cover drag selection, cancellation, busy locks, duplicate-save
prevention, failed-save draft preservation/retry, mixed-distance warnings,
invalid distance rejection and compact/high-DPI controls.
The 12600-record import retained cross-page note edits and deselection, and
verified exactly 12599 persisted records. Original database/sample hashes
remained unchanged. These bring installed coverage to 24 distinct suites.

The installed window-size suite also passed in the same evidence directory:
13 size/zoom combinations from 800x600 to 1920x1080, including 125% and 150%
zoom, plus maximize/minimize/restore. Checks include navigation/control bounds,
50-channel rendering and nonblank model pixels. The 800x600 state screenshots
at 100% and 150% were visually inspected: controls stack and remain scrollable,
with settings retained at the upper right. Source/business hashes unchanged.
Installed evidence now covers 25 distinct suites. `git diff --check` passed.
This follow-up changed test support/docs only; production code and packages
were not changed.

## r5 Workbench/Export and Source Import Follow-up

Two additional installed suites passed (workbench display and selection/export):
`G:\thimble-release-20261104-r5\installed-workbench-export\2026-11-04T02-03-19-387Z`.
Installed coverage is now 27 distinct suites. Checks include filter/selection
consistency, grouped pagination, high-DPI controls, real PNG generation for four
plate modes and two trends, axes, legend colors, clipping, collision-free names
and visualization failure/retry.

Three source/browser import suites passed:
`G:\thimble-audit-20261104-import-followup\2026-11-04T02-03-57-215Z`.
These use real isolated Python services with failure/latency injection, not
installed Electron: live progress, mixed file outcomes, failed-file-only retry,
committed-import refresh warnings, disk-full rollback, audit/log diagnostics,
duplicate prevention and 390/800/1440 diagnostic layouts.

Actual exports exposed excessive completeness prose in replacement PNG names.
Source now keeps the filename's scope concise while retaining warnings in the
image subtitle. Source audit and initial export regression passed:
`G:\thimble-audit-20261104-export-naming\2026-11-04T02-06-05-145Z`.
This production change postdates r5 and the full-source regression. The r5
packages remain unchanged and do not contain this filename refinement.

The expanded final export regression also passed:
`G:\thimble-audit-20261104-export-naming-final\2026-11-04T02-07-28-496Z`.
It observes actual canvas text drawing to verify both the no-record and
incomplete-maintenance explanations remain in the PNG, while asserting those
phrases are absent from its filename. Final `git diff --check` passed.

## r5 Installed Visualization Follow-up

Three newly package-enabled suites passed: visualization analysis, history,
and workspace. Each packaged launch asserts `app.isPackaged`; the workspace
test retains the source app-path assertion for development runs.
Evidence:
`G:\thimble-release-20261104-r5\installed-visualization-followup\2026-11-04T02-10-33-138Z`.
Installed evidence now covers 30 distinct configured suites.

The QA question was whether chart summaries, selected history and per-tube
maintenance represent the same database scope. Checks cover arithmetic against
API snapshots, site/unit/outage filters, actual outage order and missing rounds,
maintenance-only rounds, inherited/combined state, replacement counts,
settings threshold synchronization, hidden-view invalidation/reopening,
full-screen layout, PNG generation, empty states and compact layouts.
The 600-pixel plate screenshot was visually inspected: centered title,
50 channels, direction/axis labels and reachable actions.
Existing cross-window maintenance refresh evidence remains in the earlier
visualization-windows suite; these three runs do not independently prove every
possible mutation path or every chart's cross-window refresh.

No production edits were made in this follow-up. r5 still predates the
filename-only source refinement described above. `git diff --check` passed.

## r6 Broad Regression And Overview Race

The pinned r6 packaged executable passed 29 configured suites:
`G:\thimble-audit-20261104-r6-broad\2026-11-04T03-18-40-104Z`.
This covers the reviewed model, report, state, filter, account and refresh paths;
it does not claim exhaustive behavior coverage.

Further latency injection found two reproducible stale-overview bugs:

- A workbench overview captured before deletion could arrive after the
  post-delete overview and restore its obsolete count and scope options.
- Report refresh reused an in-flight overview captured before deletion.
  The report retained a deleted site's options after the last rows were removed.

The deletion regression holds actual overview responses while deleting the last
three synthetic records. The r6 reproduction failed with `3 !== 0`.
After protecting the workbench, the report-only assertion still failed.
Evidence is under `G:\thimble-audit-20261104-overview-race-before` and
`G:\thimble-audit-20261104-report-scope-race-before`.

Workbench overview now accepts only the latest request result (and error).
Report refresh and database-change events force a new overview request; stale
results cannot restore old options or clear a newer loading promise.
The expanded regression also restores the records and reselects the recovered
report scope to verify all three source rows return.

Source regression for the initial fix passed deletion, report draft/layout,
settings linkage and release lifecycle:
`G:\thimble-audit-20261104-overview-race-fixed\2026-11-04T03-44-06-020Z`.
These production fixes postdate r6. r6 must not be reported as containing them.
An independent r7 build and packaged rerun are pending at this checkpoint.

### r7 Verification

Both fixes are now present in r7. The NSIS installer exited with code 0 and
installed into `G:\thimble-release-20261104-r7\installed`.
Twelve affected suites passed against that actual installed executable:
`G:\thimble-release-20261104-r7\installed-regression\2026-11-04T03-56-40-390Z`.
The expanded deletion test verifies delayed workbench and report overviews,
clearing the final scope, and restoring the scope and exact three source rows.
Workspace-refinement and professional-UI suites now explicitly support packaged
execution and assert `app.isPackaged`; both passed in that run.

The installed clean-start test passed with 162 matching UI asset hashes:
`G:\thimble-release-20261104-r7\clean-start\packaged-clean-1793764979038`.
The actual portable launcher passed first-admin setup, empty local database,
model pixels, clean exit and backend shutdown:
`G:\thimble-release-20261104-r7\portable-start\portable-launch-1793765054033`.
Build tools were PyInstaller 6.22.0, Python 3.14.3 and openpyxl 3.1.5.
No runtime packages were replaced after these tests.

`release-manifest.json` in the r7 output records product SHA-256 values,
the bundled backend match and reviewed-source matches in the installed ASAR.
ASAR checks found no tests, user profiles, database files or RPT source data.
Source audit, `npm run check` (105 ESM files), `git diff --check` and read-only
integrity checks on both local source databases passed. Python's earlier
407-test result was not rerun here because backend sources were unchanged.

The r6 29-suite result and r7 12-suite result concern overlapping suites and
different immutable runtime snapshots; they must not be added as distinct
coverage. This checkpoint verifies the documented behavior and regression
scenarios, not all conceivable user actions or interruption sequences.

## Historical State Read Failure Follow-up

The r7 installed executable reproduced another refresh defect: after a batch
was committed successfully, `/api/states` succeeded but `/api/states/scope`
failed. The application incorrectly announced complete success. Reproduction:
`G:\thimble-audit-20261104-history-refresh-before\2026-11-04T04-11-31-855Z`.

Single and batch saves now check the historical-state refresh result separately
from the committed mutation. Failed reads display a saved-but-refresh-failed
warning and cannot present old effective states as current. A read-only retry
remains available beside the plate, including in batch mode. Read errors persist
through tube selection and view changes. Read requests time out after 20 seconds;
switching scope or forcing a newer read cancels the previous request. Write
requests are not automatically retried.

The extended source batch suite passed:
`G:\thimble-audit-20261104-history-refresh-extended\2026-11-04T04-22-37-719Z`.
It verifies batch and single committed writes with failed historical reads,
retry without another write, a subsequent explicit edit using the current
revision, timeout recovery, and cancellation of a delayed previous-outage read.
One intermediate test tried to convert a plugged tube directly to shifted;
the backend correctly rejected it. The test now uses a separate unmaintained
tube, preserving that existing business safeguard.

The new production edits postdate r7. An independent r8 build and actual
installed-package verification are required before reporting them as delivered.

### r8 Verification

The r8 NSIS installer completed with exit code 0 in an independent G-drive
directory. Fifteen configured suites passed against the actual installed
executable:
`G:\thimble-release-20261104-r8\installed-regression\2026-11-04T04-29-15-906Z`.
Coverage includes lifecycle, workbench, batch/single state maintenance, status
changes, dark mode, visualization windows and accuracy, source-record failure
handling, settings linkage, account permissions, control alignment, report
layout, professional UI and deletion/restore refresh.

The final expanded state suite also passed after improving screenshot capture
to dismiss the transient notification and scroll the persistent read-retry
notice into view:
`G:\thimble-release-20261104-r8\state-final-evidence\2026-11-04T04-34-47-373Z`.
This repeats the same suite and is not additional distinct coverage. Light/dark
and 800-pixel high-DPI error-state screenshots were inspected.

The fresh Python full run passed all 407 tests:
`G:\thimble-release-20261104-r8\python-validation\2026-11-04T04-34-15-547Z`.
Twelve source-audit/unit groups passed:
`G:\thimble-release-20261104-r8\source-validation\2026-11-04T04-34-15-545Z`.
`npm run check` (105 ESM files) and `git diff --check` passed.

Installed clean start passed first-administrator creation, empty database,
162 matching UI asset hashes, model rendering, exit and service shutdown:
`G:\thimble-release-20261104-r8\clean-start\packaged-clean-1793766555913`.
The actual portable launcher passed the corresponding first-start and shutdown
checks with exit code 0:
`G:\thimble-release-20261104-r8\portable-start\portable-launch-1793766622693`.

`release-manifest.json` verifies installed production source hashes, the bundled
backend and both product hashes. No tests, user profiles, database or RPT files
were found in the ASAR. `database-integrity.json` records read-only integrity
checks on the two existing databases; both returned `ok`.
The backend uses Python 3.14.3 and pinned PyInstaller 6.22.0.

The release report is `G:\thimble-release-20261104-r8\验收记录.md`.
r7 and older packages remain unchanged. This verifies the listed scenarios;
it does not claim every chart, mutation route or possible interruption sequence
has been exhaustively tested in r8.

## Backup List And Restore Session Follow-up

Two additional defects reproduced against the actual r8 installed executable:

- A delayed backup-list response captured before another manual backup could
  replace the newer list and hide the newly created backup's restore button.
  The snapshot file itself remained intact.
- Real restoration from the separate settings window invalidated database
  sessions but left the main window displaying its old authenticated workspace.
  Settings also navigated to a login URL without preserving its window query.

Reproductions are under `G:\thimble-audit-20261104-backup-recovery-before`
and `G:\thimble-audit-20261104-restore-session-before`.
The new `backup_recovery_desktop.mjs` uses an isolated two-row database, actual
backup/validation/restore endpoints, and the native settings window.

Backup list success/error updates now require the latest request. A failed
latest list clears obsolete restore controls. A backup committed before a
reload failure gives a distinct warning and a read-only list-refresh path.
Successful restoration immediately broadcasts session invalidation to open
windows, preserves each window's original path/query and explains the reason
at login. One successful login resumes other waiting login windows only after
checking the authoritative authenticated session.

Source settings/account/backup regression passed:
`G:\thimble-audit-20261104-backup-recovery-fixed\2026-11-04T04-49-24-654Z`.
Expanded backup, export, settings linkage and lifecycle checks passed:
`G:\thimble-audit-20261104-backup-recovery-source-final\2026-11-04T04-52-14-970Z`.
Checks include cancelled delayed validation, committed backup with failed
listing, restore failure/retry, busy-state duplicate prevention, a real safety
snapshot, removal of post-backup state on restore, failed login isolation,
and recovery of the main/settings window roles.

The new front-end fixes postdate r8. Independent r9 packaging and actual
installed verification remain pending at this checkpoint. The backend is
unchanged from the r8 binary whose full 407-test run passed.

### r9 Packaging Rejected

The r9 clean-start test rejected the build: the HTTP-served `local-auth.css`
hash did not match current source, despite the Electron ASAR containing the
new file. Investigation confirmed `build-backend.ps1` embeds the entire UI
inside the PyInstaller executable. Reusing r8's backend was an incorrect build
decision even though Python source had not changed. The installed program
serves that embedded UI, so r9 cannot be reported as containing the new fixes.

Failed clean-start evidence is under
`G:\thimble-release-20261104-r9\clean-start`.
Any passing r9 suites concern the old served frontend, not the reviewed fixes.
r9 is rejected and will not be delivered. r10 requires a fresh backend build,
fresh packages and successful HTTP asset verification before acceptance.

### r10 Installed Verification

r10 rebuilt the backend, including its embedded desktop UI, and both Electron
packages. The installer completed with exit code 0. Eleven suites passed against
the actual installed executable:
`G:\thimble-release-20261104-r10\installed-regression\2026-11-04T05-13-20-751Z`.
These cover backup/restore, local accounts and permissions, settings, lifecycle,
batch states, dark dialogs, visualization windows, UI, deletion/restore and
native export. The earlier focused backup run repeats coverage and is not added
to this count.

The clean-start run verified 162 HTTP-served UI assets against current source,
administrator creation, an empty isolated database, model rendering and shutdown:
`G:\thimble-release-20261104-r10\clean-start\packaged-clean-1793769117331`.
The actual portable launcher passed:
`G:\thimble-release-20261104-r10\portable-start\portable-launch-1793769200768`.
Twelve audit/unit groups passed under
`G:\thimble-release-20261104-r10\source-validation\2026-11-04T05-17-12-019Z`.
`npm run check` passed with 106 ESM files. Both existing databases returned `ok`
through read-only integrity checks. Python implementation sources did not change;
the earlier r8 result remains 407 passed and was not rerun in this checkpoint.

### Login Contrast Follow-up

Visual review of the native 800 x 600 window at 150% zoom found dark login
labels too dim. The previous geometry assertions passed but did not check text
contrast. An added assertion reproduced the issue against the installed r10:
labels measured 2.22:1 and password placeholder text 3.36:1 against their actual
backgrounds. Evidence:
`G:\thimble-audit-20261104-login-contrast-before\backup-recovery-1793769675006`.

Login labels now use the theme's primary text color, placeholders and footnotes
use the theme's secondary text color, and dark login errors use a readable red.
No navigation, control placement or account behavior is changed. Regression
checks now require at least 4.5:1 for visible labels, placeholders and feedback
in both themes, including an actual failed login.

These final CSS changes postdate r10. r10's earlier functional passes do not
verify this contrast fix. A fresh r11 backend and packages must be tested before
the updated release is delivered.

## Depth Distribution Axis Contract

The existing Electron depth histogram answers how many physical tubes fall
within each 5% depth interval for the selected unit and outage. It retains one
maximum valid WAR depth per tube, NDD as a separate category, and the existing
omission of missing/unconfirmed depths. Numeric bins remain [0,5), [5,10), ...
[95,100]; display thresholds and colors still follow local settings.

Native screenshot review found NDD and the numeric 0 tick visually touching in
the compact detached window:
`G:\thimble-release-20261104-r11\installed-regression\2026-11-04T05-28-08-587Z\visualization-windows-1793770247154\distribution-compact.png`.
The repair reserves a separate NDD column and a fixed gap before the numeric
axis. Numeric spacing, bar positions and threshold positions use the same
0-100 scale. NDD remains gray/configurable and is not a numeric zero. Counts,
source-record click actions and export behavior remain unchanged.

The final QA surface is the existing native Electron histogram at full and
compact sizes, in light/dark themes, with PNG export retained. Automated checks
must compare actual SVG label rectangles and numeric tick spacing. This is a
layout repair to an existing application renderer, not a new report or chart
runtime.

### r11 Checkpoint And Axis Regression

r11's eleven installed suites all passed:
`G:\thimble-release-20261104-r11\installed-regression\2026-11-04T05-28-08-587Z`.
The installed clean start verified all 162 served assets:
`G:\thimble-release-20261104-r11\clean-start\packaged-clean-1793770088605`.
The final actual portable run additionally compared the changed authentication
and backup UI files:
`G:\thimble-release-20261104-r11\portable-final\portable-launch-1793770250826`.
Twelve audit/unit groups and the 106-file ESM check passed. Existing databases
passed read-only integrity checks. Native login screenshots were inspected;
dark label contrast is now 13.09:1, placeholder/info text 7.51:1 and error text
7.89:1.

The stronger histogram-axis test subsequently reproduced a -0.81-pixel gap
between NDD and 0 in r11:
`G:\thimble-audit-20261104-histogram-axis-before\visualization-windows-1793770486646`.
After the axis layout repair, source visualization-window, accuracy and control
suites passed:
`G:\thimble-audit-20261104-histogram-axis-fixed\2026-11-04T05-35-48-246Z`.
The compact screenshot was inspected and now separates the category and zero
tick. These chart edits postdate r11; r12 packaging and installed verification
are required for final delivery.

### Histogram Export Follow-up

An actual click of the histogram's PNG export reproduced an uncaught
`Cannot read properties of null (reading 'textContent')` error and left the
button busy. Evidence:
`G:\thimble-audit-20261104-histogram-export-before\visualization-windows-1793770958770`.
The histogram uses an h3 heading while the shared exporter assumed h2; metadata
construction also occurred outside the error/finally handler.

Export now reads the existing panel heading safely, includes metadata generation
within its error/finally handler, and names the histogram PNG using the locally
selected unit and outage. Regression clicks the actual histogram export button,
injects a failed save followed by retry, checks a valid PNG, verifies its centered
title and unit/outage subtitle, and retains the resulting PNG as evidence.
The r12 backend must be rebuilt after this additional frontend edit.

### r12 Installed Verification

r12 was rebuilt after the final runtime edits, including histogram export
metadata and detached-window scope synchronization. The installer exited with
code 0 and installed into `G:\thimble-release-20261104-r12\installed`.
Five affected suites passed against that actual installed executable:
`G:\thimble-release-20261104-r12\installed-regression\2026-11-04T05-52-14-567Z`.
These are visualization windows, visualization accuracy, visualization controls,
native export, and backup recovery. They are not added to the earlier r11
eleven-suite count because the runtime snapshots and suites overlap.

Native window tests verify NDD/zero spacing, a linear numeric scale, histogram
export failure/retry, the centered PNG title, selected-unit/outage filenames,
and scope captions after both unit changes. The exported PNG and the native
800 x 600 login at 150% zoom were inspected. Dark label, placeholder/info and
error contrasts exceed 4.5:1, and the login content does not overflow horizontally.
The selected unit/outage subtitle omits internal binning filename notation.

Twelve source-audit/unit groups passed on the final runtime sources:
`G:\thimble-release-20261104-r12\final-validation\2026-11-04T05-49-22-348Z`.
`npm run check` passed with 106 ESM files. The final source window suite passed
under `G:\thimble-release-20261104-r12\final-source`.
The Python implementation did not change; the r8 full 407-test result is retained
as prior evidence, not described as a new r12 Python run.

Installed clean start checked first-administrator setup, an empty isolated
database, 162 source-matching HTTP-served UI files, model rendering and shutdown:
`G:\thimble-release-20261104-r12\clean-start\packaged-clean-1793771534843`.
The actual portable launcher passed first-start/shutdown and ten selected
served-file hashes, including the changed chart, login and backup modules:
`G:\thimble-release-20261104-r12\portable-start\portable-launch-1793771603958`.

`database-integrity.json` records read-only `ok` results for both existing
databases. `release-manifest.json` verifies the installed backend, reviewed ASAR
runtime files, HTTP asset evidence and both final product hashes. The ASAR has
no tests, user profiles, databases or RPT source data.
The backend SHA-256 is
`2a2049f504548e460ac9745454ca41f238a50c0fd93d8aec693442be8575ff30`.
Final test screenshots are written directly beneath the G-drive evidence
directory using native window capture. Runtime sources remain unchanged after
building; acceptance documentation is updated after testing.

The final installed window rerun passed after replacing the redundant system
temporary screenshot with native window capture saved directly to G:
`G:\thimble-release-20261104-r12\final-window-evidence\2026-11-04T05-58-08-121Z`.
Its native compact chart screenshot was inspected. This is a repeated window
suite, not a sixth distinct installed suite. Final product hashes remain
unchanged, and the final `git diff --check` passed.

### RPT Selection Follow-up

The next audit reproduced a different report-selection rule in the two latest
policies. Suggested latest sorted by path while automatic latest sorted by
modification time. A fixture named Report-v9 with an older modification time
was incorrectly suggested ahead of the newer Report-v2. Both source and the
actual r12 installed application reproduced the failure:
`G:\thimble-audit-20261104-rpt-latest-before\2026-11-04T06-09-53-918Z`
and
`G:\thimble-audit-20261104-native-import-before\2026-11-04T06-13-02-693Z`.

Both policies now share one selector: newest modification time first, then
numeric-aware filename order and a stable path tie-breaker. Suggested mode
still requires each group to be confirmed; manual mode still permits an older
report to be chosen explicitly. The setting description states the same rule.

The import-wizard regression now also runs the actual packaged Electron
application, including native picker IPC with isolated file-picker responses.
The chosen files, workbook inspection, mapping, database writes and refreshes
use real application paths. Synthetic report candidates are explicitly
intercepted to verify timestamps, numeric filename ties, manual override and
the confirmation requirement.

Four source import/recovery suites passed:
`G:\thimble-audit-20261104-import-fixed\2026-11-04T06-11-15-493Z`.
The r13 packaged runtime passed the strengthened wizard and cross-group
review suites:
`G:\thimble-release-20261104-r13\native-regression\2026-11-04T06-17-16-806Z`.
Repeated Escape and Cancel after a successful rollback/restore did not submit
any batch mutations. The suspected stale-dialog cancellation issue was not
reproduced and no dialog fix is claimed.

The cross-group test now counts the workbench and report center overview
requests separately. Each module has its own overview state and correctly
refreshes once. The former total-of-one assertion incorrectly treated these
two consumers as one; production refresh behavior was not changed.

The first r13 full functional run had one disk-full error among 407 Python
tests and an import-progress timeout caused by the 64 MB free-space guard:
`G:\thimble-release-20261104-r13\source-functional\2026-11-04T06-15-54-951Z`.
These results remain failed evidence, not a successful full regression.
The initial installer build also ran out of output space. A subsequent
combined build hit cleanup failure after an intermediate archive was moved;
it is not recorded as a successful combined build. A separate portable build
and full functional rerun are required.

Old release directories and formal databases were preserved. Only this
continuation's generated runtime/evidence folders were NTFS-compressed.
Automatic policy rejected removal of the new orphan extraction directory;
that directory was retained. Build scratch and isolated installation may use
the system temporary directory, while all final products, logs, screenshots
and test-result records remain on G.

### r13 Final Results

The complete rerun passed all 407 Python tests and the live import-progress
suite:
`G:\thimble-release-20261104-r13\final-functional\2026-11-04T06-24-44-528Z`.
Twelve audit/unit groups and the 106-file ESM/source checks passed.

The installer exited with code 0 into the isolated system-temporary target
`C:\Users\22234\AppData\Local\Temp\thimble-install-r13`.
Two affected suites passed against that actual installed executable:
`G:\thimble-release-20261104-r13\installed-regression\2026-11-04T06-26-49-046Z`.
Installed clean startup verified first-admin creation, an empty isolated
database, model rendering, clean shutdown and all 162 HTTP-served UI hashes:
`G:\thimble-release-20261104-r13\clean-start\packaged-clean-1793773647310`.

The portable-only build exited successfully. Its actual launcher passed
first-start/login, settings, model and shutdown checks:
`G:\thimble-release-20261104-r13\portable-start\portable-launch-1793773656319`.
The tested portable file was moved to the final G-drive product directory
without changing its SHA-256. Both existing databases passed read-only
integrity checks. `release-manifest.json` verifies the installed backend and
ASAR modules, the served UI hashes and both products.

Final SHA-256:

- Backend: `514ee898658e43a3c944bded4a76ea00a2d2a7624654dfe60f65c442942cac34`
- Portable: `bdaa868ed77f8ab75ba0e50dda80aa0adbd8c22f7bf0aafde9638fe13cb53b1b`
- Installer: `9a3ea37b10e67e7b5956078673bca3865865f84ea1d80f510c4a02074f5b4294`

The r13 native check count is two affected installed suites, not a new full
all-module desktop regression. The earlier standalone runtime run repeats
those same suites and is not added to the installed count. Acceptance
documentation was updated after the runtime build; UI sources remain
identical to the validated served assets.

### Inline Finding Commit and Refresh Follow-up

The actual r13 installed application reproduced a committed finding edit being
displayed as its old value when the subsequent overview request failed. The
database depth changed from 30 to 45, but the cell returned to 30 and dependent
surfaces were not notified. Saving and post-commit reads are now separate.
Committed changes notify consumers immediately; failed reads show a persistent
saved/reload notice, and retry performs reads only.

The new synthetic native suite verifies failed overview and row reads, cached
report/status-chart updates, detached trend updates, cancel, failed POST,
optimistic conflicts, maintenance recognition and responsive warning layouts.
Source and newly packaged native runs passed. The existing unified-ledger,
deletion/restore and state-maintenance suites also passed their final reruns.
All 407 Python tests, 107 ESM checks, the 361-file source audit and diff checks
passed. Both existing databases passed read-only integrity checks.

The newly built backend and standalone Electron runtime passed native save
regression and a clean C-drive launch, including first administrator creation,
nonblank 3D rendering, shutdown and all 162 HTTP-served UI hashes. ASAR runtime
modules and changed UI files were also compared to source.

G is full. The G r14 package staging directory is incomplete and must not be
used. Automatic approval policy rejected its cleanup; it was retained without
another deletion attempt. Only the C system-temporary standalone runtime is a
verified new build; no new installer or portable launcher is delivered this
iteration. The old r13 installer and portable hashes remain unchanged. Some
large files in the G r13 standalone runtime return ENOSPC on read, so that
directory is not claimed to have passed this continuation's checks.

See `保存后同步与刷新异常验收_2026-11-04.md` for evidence paths, retained failed
storage/fixture runs, the actual executable and remaining delivery limitations.

### Clear and Invalid-Filter Refresh Follow-up

The reviewed r14 standalone reproduced two further post-commit failures:
an invalid channel filter left a saved inline cell stuck in its loading
state, and a failed overview after a successful clear left old rows visible
without notifying dependent views. Both now retain an explicit committed
result and offer read-only recovery. Clear immediately invalidates old
requests, rows and maintenance caches; the loaded 3D model also receives the
clear notification. Clear labels now describe the actual preserved accounts,
logs and recovery backups.

Five source desktop suites passed. A rebuilt embedded backend and standalone
Electron runtime passed six targeted native suites, including simultaneous
overview/finding/state read failures, a delayed pre-clear overview, detached
charts, cached reports, invalid-filter recovery and UI alignment. All 407
Python tests, 108 ESM checks and the 362-file source audit passed. Clean
startup verified first-admin setup, an empty isolated database, model
rendering, shutdown and all 162 HTTP-served UI hashes. Both existing databases
passed read-only integrity checks with unchanged hashes during inspection.

The verified r15 standalone and all new evidence are on C because G remains
full. This iteration does not replace old products or deliver new installer
or portable launchers. These targeted suites are not a new all-module desktop
acceptance claim. See `清空与无效筛选同步验收_2026-11-04.md` for exact paths and
remaining coverage limits.

### State-to-Model Synchronization Follow-up (r16)

The r16 standalone executable was rebuilt in an isolated C-drive directory and
completed the four targeted desktop suites:

- workbench display and invalid-filter recovery;
- control alignment and warning layout;
- clear-business-data refresh across dependent views;
- state-maintenance to detached 3D-model synchronization.

All four suites passed. Evidence:
`C:\Users\22234\AppData\Local\Temp\thimble-audit-r16-native\2026-11-04T07-56-52-950Z`.

Executable:
`C:\Users\22234\AppData\Local\Temp\thimble-audit-r16-scratch\packages-reviewed\win-unpacked\在役检查系统-指套管数据管理工具.exe`.

The updated backend SHA-256 is
`de79ce4b7cb900d8fbdfe58473054ad1c7c3f0842d5b00219565856116a0bbe8`.
This follow-up is a targeted regression result, not a claim that every module
and every possible operation combination has been exhaustively exercised.
G remains unavailable for new evidence, and no existing release package was
overwritten.
