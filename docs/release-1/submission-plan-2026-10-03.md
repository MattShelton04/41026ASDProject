# Release 1 submission plan — 3 October 2026

This plan follows the updated Canvas brief checked on 27 September, Assessment 2 (30 marks),
and the compatible project requirements in `ASD_2026_Project_Specifications.pdf`.
Implementation scope for this branch is Shared, Feature 1, report generation and evidence tools.
Other feature implementations remain with their allocated owners.

| Task | Owner | Completion evidence / remaining action |
|---|---|---|
| Distinguish verified MCP results from ordinary HTTP tool calls | Shared / Matthew | Signed, schema-validated calls add `transport:mcp`; SDK round-trip and denial tests |
| Reject false-positive host readiness probes | Shared / Matthew | Probe checks canonical service/status/store response; 18 regressions |
| Correct all-five-feature architecture and grounding documentation | Shared / Matthew | Living architecture and AI-mode README updated |
| Count the complete report fairly and guard final builds | Shared / Matthew | Substantive appendices/code count; baseline/evidence/contribution guards; R0 preserved |
| Verify the combined local deployment | Group integration | Existing `ps-dev` stack reused; no data reset, acquisition or publication |
| Verify current accepted data and all five guidance corpora | Feature 1 / Shared | Live data-status and service-probe JSON; demo records explicitly labelled |
| Capture each feature's MCP, cited RAG and insufficient-context UI | Group integration | Verified owning-backend runs, public sidecars, image hashes and visual review |
| Check existing frontend/API/persistence behaviour | Group integration | Safe live operations capture; temporary labelled audit records cleaned up |
| Repair Sources layout in narrow embedded assistants | Shared / Matthew | Container-responsive layout, focused browser checks and recapture |
| Fill contributions, attendance and showcase link | Report / all owners | Identifiable merged commits; Matthew confirms all five participated on 2 October |
| Verify presentation metadata | Report | Public page loads; title “ASD Release 1 Full Demo”; 575 seconds. Review playback/coverage before uploading |
| Independently mark the draft and resolve report gaps | Group integration | Two rubric reviews aggregated; conservative count, focused evidence, named NFRs, contribution dates and list order improved; all 34 draft pages checked |
| Update root README to tested setup/status | Shared / Matthew | Correct ports, host services, corpus setup, evidence links and limitations |
| Run canonical quality gate; commit and push a reviewable PR | Shared / Matthew | Final local gate passed: 2,444 Python tests and 238 JavaScript tests; 80 prerequisite/platform skips. PDF built at evidence baseline `efe8921`; see this branch's PR for remote checks |
| Submit one `group-20.pdf` by 4 October 23:59 Sydney | Designated group uploader | PDF within 3,000 words plus diagrams; tutor-visible repository and video |

## Owner follow-ups outside this branch

| Feature | Required follow-up | Acceptance check |
|---|---|---|
| 2 / Burhan | Clear assistant history and update scope when the selected market case changes, including an active run | Switch A→B; a B question cannot reuse A's context/history; cancel/rebind active request safely |
| 4 / Michael | Native generated-question renderer accepts grounded finding objects and `next_step` | Successful grounded response shows meaningful follow-up questions rather than dropping structured findings |
| 5 / Derek | Reconcile the offline AI-mode start in `student-5.yml` with the brief's broader AI-mode-disabled instruction | Feature frontend/API/database CI succeeds without starting host AI; MCP/RAG remain disabled |
| All | Validate showcase coverage and each member's Q&A preparation | Show owned feature, MCP result, cited answer and insufficient context; explain boundaries and limitations |
| All | Recheck successful assigned workflow links for any subsequently changed feature | Preserve the tested SHA, workflow path and run URL; do not label earlier success as a later commit's result |

These follow-ups are explicit submission risks. Passing the PDF guard does not establish full
software correctness, original approval provenance or a guaranteed mark. No source datasets were
downloaded, published or replaced for this report task.
