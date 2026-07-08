# Krukit Flow: v1-live-validation
Started: 2026-07-08 | Route: fix
Task: Live-validate Yoke v1 against docs/manual-qa-checklist.pdf; TDD-fix defects surfaced by the live run
- [x] 1 recon — skipped (route) 2026-07-08
- [x] 2 grill — skipped (route) 2026-07-08
- [x] 3 design — skipped (route) 2026-07-08
- [x] 4 plan — skipped (route) 2026-07-08
- [x] 5 act — done 2026-07-08, artifact: src/sources/hn.py + tests/test_source_hn.py, README.md
- [x] 6 verify — done 2026-07-08, artifact: verify.md

## Act — pre-run finding (2026-07-08)
BROKEN PREMISE: docs/manual-qa-checklist.pdf targets a full web-UI product
(`./yoke serve` control panel; Settings/Profile/Board/Apply/Reject/Applied/
Improve/Schedule pages; `collect/status/gap/cover/tune/eval` CLI). Built v1 is
CLI-only: `run` (collect→prepare→analyze→board→SHORTLIST.md), `board`, `apply`,
`drop`. No web server, no HTML, no eval/tune (README marks those "roadmap").
~1.5 of 14 checklist sections map to reality. Live-validation against this
checklist as-written is impossible. Awaiting user scope decision before act.
- [x] 7 review — skipped (route) 2026-07-08
