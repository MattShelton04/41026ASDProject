# Diagnose an acquisition or import failure

Read the failed run's phase, structured error, task progress, source scope and artifact evidence before naming a cause. Acquisition, artifact verification, typed staging, candidate materialisation, quality checks and release construction are distinct stages. A failure label alone does not prove a checksum error, network fault or exhausted disk space.

After correcting an import failure, Use downloaded file creates a cached reprocess from retained verified evidence with the same scope and lineage. It creates a new candidate, does not redownload by default, and cannot overwrite an accepted artifact. A partial PSI scope remains partial and non-publishable after reprocessing. A failed or cancelled candidate import does not activate candidate data. Report unavailable diagnostic evidence instead of guessing a repair or issuing destructive database commands.

Basis: student-1 README, cached reprocessing and durable worker phases; ADR-035.
