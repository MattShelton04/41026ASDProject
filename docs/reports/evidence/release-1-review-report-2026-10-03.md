# Independent Release 1 report and evidence review

Review date: 3 October 2026, Australia/Sydney. Branch: `Matt/Release_1_Report_Updates`.

This review applies the current [Assessment 2 rubric](https://canvas.uts.edu.au/courses/39716/assignments/268214), using the complete local copy in `C:/git/Uni/courses/41026-advanced-software-development/assignments/268214--assessment-2-release-1-mcp-rag-intelligent-agent-integration.md`. It reviews the rewritten [report source](../release-1-technical-report.md), fresh public evidence and relevant implementation. The earlier submitted-location draft PDF and its old placeholders are not grading evidence for this review.

The rewritten report is substantially ready for assessment. The shared runtime, all five feature integrations and selected successful MCP/RAG/refusal scenarios are demonstrated. A defensible provisional estimate is **25/27 for the nine assessable criteria**, with **criterion 10 ungraded (0-3)** because repository evidence cannot establish Q&A quality. With full-mark demonstration/Q&A this implies approximately **28/30**. This is a reviewer's estimate, not a marker's decision. The remaining Feature 2/4 functionality issues prevent an unqualified prediction of 30/30.

## Evidence boundary

- All 15 assistant sidecars show successful real configured-provider runs through the owning frontend/backend, with correct feature/corpus identities. Every retained image hash matches its sidecar.
- Each MCP scenario includes its expected successful `transport:mcp` call. Each RAG scenario retains cited guidance and a confidence category. All five unsupported-question scenarios have insufficient confidence and zero answer citations.
- Feature 2's refusal has a `ready` retrieval but `insufficient_context` grounding: related passages do not support password instructions. It must not be described as a retrieval `no_match` case.
- The shared probe shows 29 exposed feature tools, all five ready corpora and relevant/no-match retrieval checks. The live versions contain 19/3/8/3/5 documents. These are authored guidance corpora, separate from accepted property datasets.
- Named MCP/RAG loop outputs use deterministic decisions against live services. They prove transport and Plan/Act/Observe/Adapt execution, not provider answer quality.
- The operations record demonstrates frontend/API access and owning-store reads for every feature, with create/read/update/delete and cleanup for Features 1 and 4. Counts for Features 2/3/5 demonstrate persisted reads; they do not independently demonstrate every CRUD action.
- The 3 October status contains 20 running containers and three separate host AI processes. Eighteen containers have healthy healthchecks; the Feature 1 runner and loader have none.
- Six retained GitHub runs succeeded at `330e65f`, covering all five merged integrations and Integration CI. They precede the report-update branch. Their success cannot be relabelled as CI success for later shared/runtime changes.
- The retained unauthenticated YouTube check reports HTTP 200 and 575 seconds (9:35). `coverage_reviewed` is false. Matthew's confirmation establishes that all five attended and participated on 2 October; it does not establish how well they explained and defended their work.
- Twelve feature capture sidecars and the two shared views record software SHA `937389a`; the three refreshed Feature 4 sidecars record `bbcbd25`. They explicitly retain a tracked-worktree dirty flag. The final report baseline must include the captured software/evidence and must not describe these as clean-checkout captures without further verification.

## Criterion-by-criterion estimate

| Criterion | Estimate / 3 | Reason and full-mark condition |
|---|---:|---|
| 1. Project setup and architecture | 3 | Updated repository structure, overall architecture and frontend/backend/MCP/RAG flow are present. Host/container and owning-database boundaries agree with the code and runtime evidence. |
| 2. Student feature microservices | 2 | Every feature is integrated and the selected paths work. Feature 2 case switching can retain an old conversation/context; Feature 4's legacy question-pack extraction does not fully support grounded findings. Full marks require the assigned Release 0 functionality and AI-mode to continue working correctly, including these paths. An unaffected individual feature may earn 3. |
| 3. MCP server integration | 3 | Tool registration, field/schema summaries, access/approval boundaries, terminal validation and successful frontend/backend MCP transport exist for all five features. |
| 4. RAG and grounded responses | 3 | Each feature has a retrieved-context answer with citations/confidence and a demonstrated unsupported-question response. Sources, retrieval design and terminal checks are documented. The disclosed exploratory Feature 4 adaptation failure remains a reliability limitation rather than a successful refusal. |
| 5. Shared agentic loop | 3 | Both distinct validation modes complete all four phases against live services and their captured outputs appear in the report. Deterministic decision provenance is explicit. |
| 6. DevOps and GitHub Actions | 3 | Every assigned workflow has a successful run and disables MCP/RAG, matching the precise full-mark criterion. The brief separately says AI-mode must also be disabled; Feature 5 starts offline direct AI-mode. This inconsistency remains a broader compliance risk, potentially costing one point if the marker applies that instruction. |
| 7. Docker Compose deployment | 3 | Running-container status, application access and host connection configuration demonstrate integrated deployment without AI services in Compose. Final baseline should retain current execution evidence. |
| 8. Integrated working software | 2 | All five required selected MCP/RAG paths succeed, but the Feature 2/4 residual functionality defects prevent describing the complete application as fully operational without qualification. Full marks require fixing and validating those paths. |
| 9. Technical report and project evidence | 3 | The revised source covers scope, requirements, NFRs, architecture/design, validation, limitations, all five dated contribution records, identifiable commits and repository/video links. The final PDF is readable and pins all repository source links to the verified evidence baseline. Remote access and submission still require the group handoff. |
| 10. Demonstration and Q&A | Ungraded, 0-3 | All five participated according to the user's confirmation. Actual explanation, defence and accurate understanding were not observed by this reviewer; public access and video duration are not substitutes. |

**Assessable subtotal: 25/27.** A marker may judge the remaining functionality defects as minor or outside the selected demonstration, producing 26-27/27; the broader CI instruction can instead reduce the estimate. Full-mark Q&A adds three points only when the marker observes the required understanding.

## Prioritised remaining tasks

### 1. Fix the actual feature regressions through the owners

**Feature 2, Burhan:** `student-2/frontend/app.js` reuses the assistant and calls `controller.setContext` on case change. `shared/frontend/ai-chat/controller.js` refuses context updates while a turn is active and does not clear completed turns/history when idle. Reset or recreate the case conversation on a trusted selected-case change. Verify switching cases during an active turn, switching after completion, follow-up history and deletion of the selected case. The selected-case display, trusted backend case identifier and conversation history must agree.

**Feature 4, Michael:** `student-4/frontend/models.js::extractQuestions` extracts strings from `findings` and the legacy `recommended_next_step`, whereas grounded findings are typed objects containing `text` and use newer answer fields. Preserve the original question-pack behaviour through the owning renderer/backend contract. Verify the native Generate questions path with a real grounded completion and deterministic typed-finding regressions. Shared chat success does not establish that this separate Release 0 button still works.

These are owner implementation tasks. Recording them as limitations is honest but does not itself satisfy the rubric's fully-operational standard.

### 2. Resolve the Feature 5 CI instruction conflict

The precise rubric and workflow responsibility rows require MCP/RAG disabled; the brief's introductory bullet additionally requires AI-mode disabled. `.github/workflows/student-5.yml` deliberately starts host AI-mode using `--mode direct --offline`. The report correctly discloses this. The owner should either use deterministic doubles without starting AI-mode or obtain an explicit interpretation permitting the offline direct smoke, then retain a successful updated workflow. Do not silently relabel the existing run as AI-mode-disabled.

### 3. Freeze and publish the traceable report baseline

The final builder passed using evidence baseline `efe89219a0c6e66a4ebafe7d27b06c1eec1a4ba8`, which contains the report source/figures, capture sidecars and public evidence. Publish that baseline and the final artifact/reviews so the tutor can resolve their links, and obtain successful workflows for the final integration changes. The parent reports the required full quality gate passed after the last code change: 2,444 Python tests and 238 JavaScript tests, with 80 optional/platform skips. Keep earlier `330e65f` runs labelled as earlier evidence. The final builder checks commit existence/ancestry, covered sections and unchanged tracked evidence, but does not prove remote accessibility, CI success or semantic answer quality.

### 4. Review the video and final submission with a human

Confirm the 9:35 video shows each student demonstrating their assigned feature's MCP and RAG interactions through UI/backend, direct terminal MCP/RAG validation, and both loop modes. Verify tutor access to the repository and video. Preserve the truthful attendance statement and avoid predicting individual Q&A marks from attendance. Upload one `group-20.pdf` from one group member before 4 October 2026, 23:59 Sydney time.

### 5. Preserve final PDF QA and conservative word counting

The generator now conservatively includes cover text, captions, substantive appendices and fenced evidence. The final report count is **2,785 words**, below the 3,000-word ceiling. Rerun word counting and final generation if assessed report content changes. No appendix or code exemption is being assumed.

The focused answer and citation cards resolve the earlier small-screenshot concern: the fresh draft prints all 15 answers and five source passages at readable sizes, while linking the original full UI captures and metadata. Dense tool tables and diagrams fit. The discovered multiline-list rendering defect was repaired in `09f0f21`: list continuation lines now remain inside their preceding bullet. The corrected Known issues section preserves reading order on pages 33–34. Supplementary `.sources.png` images show source excerpts and recorded calls; the PDF includes the five selected `.citation.png` cards.

## Source accuracy and scope notes

- The updated maintainability/interoperability/availability NFR rows and dated contribution links resolve the initially observed report omissions. The report should retain explicit validation boundaries for measured recall and recovery tests.
- Accepted G-NAF/PSI/BOCSAR/SEIFA counts and seeded schools/fixture-property counts are separated. These counts do not establish that downstream feature evidence is complete or official. The selected Feature 4 constraints/building records are synthetic demonstrations, now disclosed in the limitations.
- An exploratory off-topic Feature 4 turn failed adaptation validation. The retained successful password refusal is valid selected evidence; neither it nor the deterministic loop establishes all-question reliability.
- The newer assessment rubric requests the overall architecture/interaction diagrams. The older general project specification additionally lists individual plans, risk plans, individual diagrams and attendance checkpoints. The linked release audit and existing architecture records help conservatively cover those requests; this review does not deduct current-rubric points merely for the absence of a separate diagram per student.
- No new stack start, data acquisition/publication, provider request, destructive operation or tracked implementation edit was performed by this reviewer. All live claims above describe inspected retained artifacts captured by the main task.

## Fresh PDF QA addendum

Reviewed the corrected `Temp/release1-review/group-20-draft.pdf`, SHA-256 `0117a3aa769eb6336b320e730c6798db6e765f5f6dd62bf7a7ffd7aba1671f41`, 2,528,847 bytes, 34 pages. Rendered all pages with the bundled Poppler and visually reviewed the complete corrected draft. Twenty-six page renders match previously inspected pages pixel for pixel; all eight changed pages were inspected again at full size. The initial draft digest was `cb03f612037e8275d6330e08e2a0a8c1ca72f27cb4467afdd14978ae2a521a8a`.

- All required source images are present; there are no missing-image/TODO/baseline-token/temporary-TOC markers.
- Body tables, loop evidence, answer cards and citation passages are readable and stay within the page margins. The large Feature 4 cards fit near a full page. Small shared overview screenshots serve as context; selected assistant evidence is separately legible.
- The page 33 multiline-list order defect is resolved. The refreshed Feature 4 cards have no toast corner; all answer and citation content remains readable. The grouped deployment-status table fits and correctly separates running counts, healthchecks and host processes.
- There are 60 external link annotations, including two video links, six successful workflow links and 16 direct commit links. Table of contents and PDF bookmarks are present. Repository source links currently target `main`, as expected for a draft; final generation must replace these with the full published immutable baseline.
- The original tracked draft PDF was not assessed. The final artifact confirmation below completes local builder/layout verification for the reviewed source and captures.

## Final artifact confirmation

Independently inspected [the final group-20.pdf](../submissions/release-1/group-20.pdf), **34 pages**, **2,530,105 bytes**, SHA-256 **`fe12b32e758802204ed6e784381318010a7003b39f3faee64c19a51509b5a863`**. The parent reports its `--final` builder passed at baseline **`efe89219a0c6e66a4ebafe7d27b06c1eec1a4ba8`**.

The cover correctly shows that full SHA, Group 20, the supplied presentation link, 2 October showcase and 4 October 23:59 Sydney submission time. All **34 repository source links** now use the exact immutable baseline. The PDF retains **60 external links**, including two video links, six genuine workflow links and 16 direct contribution commit links. Contents/bookmarks and page numbers remain correct, with no unfinished markers.

Rendered the final PDF at the same Poppler scale as the reviewed corrected draft. **Pages 2–34 are pixel-identical**; the only changed page is the cover's full baseline value, which was visually inspected and fits. This establishes unchanged final body layout, including the corrected Known issues list, readable answer/citation cards and grouped deployment status. No report-source change or new test run was performed by this reviewer. Remaining feature-owner corrections and human video/Q&A assessment are unchanged; final artifact QA does not remove those rubric risks.
