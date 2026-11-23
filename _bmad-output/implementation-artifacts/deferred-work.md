- source_spec: `_bmad-output/implementation-artifacts/spec-consolidate-ai-settings.md`
  summary: Manage → AI has no way to remove a saved TypeSafe key (or the AI image key without switching provider), so falling back from TypeSafe to the AI provider needs a .env edit.
  evidence: Both keys are write-only and blank means "keep"; TypeSafe is preferred whenever TYPESAFE_API_KEY is set (`_suggest_engine` in app.py). Pre-existing in the old Holiday Menu save.
- source_spec: `_bmad-output/implementation-artifacts/spec-consolidate-ai-settings.md`
  summary: The request body built by `Ai.save()` in static/js/app.js is not exercised by any test; only a hand-copied body in tests/test_menu.py covers the server side.
  evidence: Unverified (medium if true): the repo has no JS test harness (package.json only has Prettier scripts). Settled by a browser or JS unit test that runs Ai.save with blank key fields and checks saved keys survive.
