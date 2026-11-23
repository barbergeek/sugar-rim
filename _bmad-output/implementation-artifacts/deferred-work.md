- source_spec: `_bmad-output/implementation-artifacts/spec-consolidate-ai-settings.md`
  summary: Manage → AI has no way to remove a saved TypeSafe key (or the AI image key without switching provider), so falling back from TypeSafe to the AI provider needs a .env edit.
  evidence: Both keys are write-only and blank means "keep"; TypeSafe is preferred whenever TYPESAFE_API_KEY is set (`_suggest_engine` in app.py). Pre-existing in the old Holiday Menu save.
- source_spec: `_bmad-output/implementation-artifacts/spec-consolidate-ai-settings.md`
  summary: The request body built by `Ai.save()` in static/js/app.js is not exercised by any test; only a hand-copied body in tests/test_menu.py covers the server side.
  evidence: Unverified (medium if true): the repo has no JS test harness (package.json only has Prettier scripts). Settled by a browser or JS unit test that runs Ai.save with blank key fields and checks saved keys survive.
- source_spec: `_bmad-output/implementation-artifacts/spec-18-cache-menu-suggestion-judgments.md`
  summary: Chat-model answers may not be comparable across batches, so mixing stored answers with a few newly judged drinks could skew rankings.
  evidence: Unverified (medium if true): llm_prompt() asks the model to use the whole 0-10 scale across each batch of 20 drinks. Settle by judging the same drinks in one batch and in mixed batches and comparing their scores.
- source_spec: `_bmad-output/implementation-artifacts/spec-18-cache-menu-suggestion-judgments.md`
  summary: Nothing tests that the Holiday Menu actually sends the selected theme and the Start fresh checkbox state to /api/menu/suggest.
  evidence: Unverified (medium if true): no JS test harness; a dropped theme files every run under "classic". Settle with a manual check on two themes plus Start fresh, or a browser test.
