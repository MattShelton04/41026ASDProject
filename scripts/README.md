# Automation scripts

- `check.py`: cross-platform deterministic formatting, lint, type, test, and coverage gate
- `validate_architecture.py`: enforce workspace dependency and Python import ownership boundaries
- `validate_tool_catalogs.py`: fail-fast composition check for every feature tool catalogue
- `build/`: shared application and container build automation
- `test/`: shared local and integration test automation
- `deploy/`: Release 2 Azure deployment automation

Scripts should validate and operate the integrated application rather than
deploying isolated student features.
