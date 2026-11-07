- source_plan: `/home/scott/develop/sugar-rim/_bmad-output/plan-recipe-import-from-websites.md`
  summary: Recipe import UI — Manage-view "Import Recipe" card, URL / paste-HTML input modal, editable review modal (fields, ingredient rows, image include), save via /api/import/cocktail and open the new cocktail.
  evidence: User chose to split the ~2000-token plan; the scraper package and import API ship first and are verifiable via pytest and direct API calls.
- source_plan: `/home/scott/develop/sugar-rim/_bmad-output/plan-recipe-import-from-websites.md`
  summary: Verify AC2 live — POST the Food Network draft to /api/import/cocktail against a real Bar Assistant and confirm the cocktail exists with 7 ingredients and image (unverified; medium if it fails).
  evidence: Route tests mock BA; draft shape matches BA develop `Cocktail::fromSchema4Array`, but no live run was possible from this session.
- source_plan: `/home/scott/develop/sugar-rim/_bmad-output/plan-ai-image-generation.md`
  summary: Cocktail form image section — add file / URL / AI-generate image controls to the cocktail edit form (it has none today), reusing the ingredient form's image code and `/api/ai/image`, with a cocktail prompt built from name, glass, ingredients and garnish; upload on save, delete old images, send `images: [id]`.
  evidence: User chose to split the ~1900-token plan; AI generation ships first on the ingredient form and Settings.
- source_plan: `/home/scott/develop/sugar-rim/_bmad-output/plan-ai-image-generation.md`
  summary: docker-compose.yml seeds `BA_API_URL`/`BA_API_TOKEN`/`BA_BAR_ID`/`SECRET_KEY` as `${VAR:-}`, so unset vars become empty strings that override UI-saved `/config/.env` values on restart (`load_dotenv` uses override=False).
  evidence: python-dotenv main.py `if k in os.environ and not self.override` skips them; pre-existing, found in review of the AI image work.
