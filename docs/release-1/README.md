# Release 1

Release 1 retains Release 0 and adds MCP, RAG, grounded AI responses, updated
local integration, CI, architecture, testing evidence, report content, and
showcase evidence.

Start with the [Shared/Feature 1 handoff and evidence map](shared-feature-1-handoff.md), the
[reviewed implementation plan](shared-feature-1-implementation-plan.md), and
[ADR-043](../architecture/decisions/ADR-043-local-grounded-runtime.md). The marking rubric supplied
on 6 September requires non-containerised local AI-mode, MCP, RAG and agent loop; MCP/RAG stay
disabled during CI/CD. Those requirements supersede the older Compose assumptions.

- [Release 1 technical report](../reports/release-1-technical-report.md): report source, word budget
  and owner TODOs; build instructions in [reports/README.md](../reports/README.md).
- [Host runtime](host-runtime.md): lifecycle, networking, history migration and named loop validations.
- [Adopt MCP and RAG](adopt-mcp-and-rag.md): the ordered five-step checklist for feature owners,
  with the corpus template and shared assertions. Start here.
- [Feature adoption](feature-adoption.md): existing tools/backend boundary, owned corpus registration,
  grounded-run ownership and shared source UI for other feature owners.
- [Retrieval evaluation](retrieval-evaluation.md): versioned source recall and negative-case limitations.
- [Captured public outputs](evidence/README.md): real local transport modes and actual provider summaries.
- [Five-feature delivery plan](release-1-delivery-plan.md): archived-course interpretation, wider group
  requirements and submission checklist; not a claim that every owner's R1 work is complete.

Other students' feature acceptance, full group report/video, tutor decisions and individual Q&A
remain owner/human evidence. The shared/F1 increment supplies the common foundation without
claiming those separate responsibilities.
