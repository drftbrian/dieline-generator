# CLAUDE.md

Dieline Generator: a packaging dieline in, photoreal images out, with the printed artwork pixel-exact. The app is deliberately **3 steps**:
① source (Figma frame import, PDF upload as fallback) → analyze → structural review/confirm, ② one flat photoreal render, ③ merge into one reference photo.

**The user is a non-coder learning by doing.** Explain in Korean, plainly, with short analogies. Keep user-facing docs (README.md) Korean-first.

## Stack
- Frontend: Vite 8 + React 19 + TypeScript in `src/` (TanStack Query, zustand, react-router, Tailwind 4, radix-ui). Lint with oxlint.
- Backend: FastAPI in `backend/`, run with `uv`. SQLite + files under `backend/data/` (gitignored). Keys in `backend/.env`: `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `FIGMA_TOKEN` (settings in `backend/app/config.py`).
- Vite (default :5173) proxies `/api` to uvicorn on :8000.

## Architecture map

### Frontend (`src/`)
- `api/`: fetch client + TanStack Query hooks per resource (`generate.ts` has `useStartFlat` / `useStartMerge`; also figma, projects, references, history, jobs, source, spec).
- `features/`: `flat` (step 2 panel), `merge` (step 3 panel: reference drop zone, Claude's read-only reading, form 자동/평면/입체, flat-version picker), `canvas` (source / flat / merge viewer + job status), `history` (version strip), `inspector` (source facts), `review` (structural review), `analysis`, `upload`, `projects`, `studio` (top bar, shared step-panel pieces, `versions.ts` helpers).
- `pages/`: Dashboard, Analyze, StructuralReview, Studio, WorkspaceGate, NotFound. `app/`: shell, providers, router.
- `stores/`: zustand (`useCanvasStore`: view `source|flat|merge`, selected `flatId` / `mergeId`, `mergeSourceId`, toasts, UI).
- `i18n/ko/*`: all Korean UI strings.
- `types/api.gen.ts`: generated from the backend OpenAPI schema.

### Backend (`backend/app/`)
- `api/`: routers (`health`, `figma`, `projects`, `references`, `generate`, `history`), `schemas.py`, `deps.py` (`version_out`, `is_legacy`).
- `services/pipeline.py`: analyze job, structure render (`flat.jpg`), step 2 `run_generate`, shared `composite` / `verify` / `deliver`.
- `services/merge.py`: step 3 `run_merge`, carton faces, `stage`, folded `composite`, reference staleness (`REFERENCE_SCHEMA`).
- `services/brief.py`: `figma_brief` (dims, panels, verbatim texts by panel/face, fonts, logos, colours); PDF-text fallback.
- `services/specs.py`: load/save the Specification.
- `ai/claude.py`: `suggest_structure`, `name_panels`, reference reading (`AiReference`: category, 7 sections, packaging_form, camera, light).
- `ai/prompts.py` + `ai/prompts/`: `flat_render.md`, `merge.md`, `reference_guide.md`, `flat_look.png`.
- `ai/providers/gemini.py`: the single image provider; `ai/models.py`: model IDs.
- `figma/`: Figma REST client and layer/content extraction.
- `pdf/`: extraction, `dieline.py` (cut/crease/annotation classification), `rules.py` (layer-name table), measure, physical sizes, validation.
- `render/`: `layers.py` (artwork, silhouette minus openings, creases), `shading.py`, `surface.py` (light/surface transfer), `carton3d.py` (fold the box), `look.py` (`verify`, ΔE).
- `jobs/runner.py`: background jobs with stages (analyze, render, generate, merge).
- `storage/db.py` (schema, additive migrations, dropped tables), `storage/repo.py`.
- `spec/models.py`: Specification models and the fixed `FLAT_LOOK`.
- `tests/`: pytest (fake Gemini in merge tests).

## API surface (all under `/api`)
- `GET /health`, `GET /figma/status`, `POST /projects/figma`
- Projects: `GET|POST /projects`, `GET|PATCH|DELETE /projects/{pid}`, `POST /projects/{pid}/upload` (PDF), `GET /projects/{pid}/source`, `/source/file`, `/thumbnail`, `/page-image`, `/frame`, `POST /projects/{pid}/analyze`
- Structure: `GET|PATCH /projects/{pid}/specification`, `POST /projects/{pid}/specification/confirm`
- References: `GET|POST /projects/{pid}/references`, `POST /{rid}/analyze`, `DELETE /{rid}`, `GET /{rid}/image`, `/{rid}/thumb`
- Generation: `POST /projects/{pid}/generate` (`{}`), `POST /projects/{pid}/merge` (`{reference_id, flat_version_id?, form: auto|flat|folded}`), `GET /jobs/{id}`, `POST /jobs/{id}/cancel`
- History: `GET /projects/{pid}/history`, `GET|DELETE /projects/{pid}/versions/{vid}`, `GET .../image` (`?download=1`), `GET .../thumb`
- Errors are `{code, message, hint, details}` with Korean messages (e.g. 409 `STRUCTURE_UNCONFIRMED`, 503 `PROVIDER_UNAVAILABLE`, 429 `TOO_MANY_GENERATIONS`, 422 `ARTWORK_MISMATCH`).

## Invariants (do not break)
- **The model never decides the printed artwork.** The original print is always composited back over the model output (`pipeline.composite`, `merge.composite`).
- **`verify` gates every delivery.** Only `pipeline.deliver` saves a result; a failed check saves `<vid>_rejected.png` and fails the version with `ARTWORK_MISMATCH`. Never bypass or loosen it to make a result pass.
- **Prompts live only in `backend/app/ai/prompts/*.md`.** No prompt text in Python. Templates are filled with `string.Template.substitute` (missing placeholder = error); keep placeholders and their callers (`flat_prompt`, `merge_prompt`) in sync. `flat_render.md` / `merge.md` are `@cache`d: backend restart needed after edits.
- **One image provider (Gemini) + Claude for reading only.** No OpenAI.
- **Korean UI strings live in `src/i18n/ko/*`**, not inline in components.
- **`src/types/api.gen.ts` is generated: never hand-edit.** Run `pnpm gen:types` after any backend schema change.
- **Keep it 3 steps.** No library, interpret/instructions, finishes, scene builder, export dialogs or other extras. Delete rather than hide.
- Redline rule: outer outline = cut, inner lines = fold, inner closed loops = openings (black). Never remove artwork on a guess (uncertain lines stay `unresolved` for human review).
- Old data must keep loading: unknown spec keys are ignored; versions without `settings_json.pipeline == 2` are legacy; stale reference readings are re-read in the background.

## Commands
- `pnpm dev`: web (Vite) + api (uvicorn :8000, reload on `backend/app/*.py`)
- `pnpm test:api`: backend pytest
- `cd backend && uv run ruff check .`
- `pnpm typecheck`, `pnpm lint`, `pnpm build`
- `pnpm gen:types`: export OpenAPI, regenerate `src/types/api.gen.ts`
- `cd backend && uv run python scripts/check_providers.py`: check keys without generating

Do not run real AI generation calls from tests or scripts; use the fakes in `backend/tests/`.
