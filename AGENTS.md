# AGENTS.md

This file gives coding agents the project-level context needed to work safely in this
repository.

## Project Purpose

DeepResearch is a backend service for an internal AI research report workbench.

The main workflow is:

1. Create a research project.
2. Generate a research brief and outline.
3. Let the user confirm or revise the outline.
4. Run a Celery-backed research task.
5. Save structured research materials and section results to MongoDB.
6. Render the saved research result into deterministic HTML.
7. Serve the report through the API and static frontend.

The service is not a general chat app. Keep research execution, persistence, and
report rendering as separate concerns.

## Tech Stack

- Python 3.12
- FastAPI for HTTP APIs and static file serving
- Celery + Redis for background task execution
- MongoDB via async PyMongo for persistence
- Pydantic v2 for schemas and settings
- DeepAgents for research orchestration
- Ruff and pytest for validation

## Important Paths

- `app/main.py`: FastAPI app factory and static file mount.
- `app/routers/__init__.py`: API routes for projects, outlines, tasks, and reports.
- `app/background/research_tasks.py`: async task workflows called by Celery tasks.
- `app/celery_app.py`: Celery application configuration.
- `app/agents/research_agent.py`: research orchestration facade. Do not put schema
  definitions here.
- `app/agents/prompts/`: system prompts for the manager agent and search subagent.
- `app/schemas/__init__.py`: common API schemas and public schema exports.
- `app/schemas/research.py`: research-domain Pydantic models.
- `app/repository/`: MongoDB and report persistence.
- `app/tools/`: agent-callable tools and deterministic report rendering.
- `docs/simplified_research_data_model.md`: current research data model.
- `docs/simplified_research_data_model_todo.md`: migration checklist and status.
- `static/index.html`: local browser UI.
- `static/architecture.html`: architecture diagram.
- `tests/`: pytest tests.

## Current Data Model Direction

The project is migrating to a simplified research model:

```text
sources -> sections.key_findings
sources -> sections.risks
```

Use these project-level research objects:

- `sources`
- `sections`

Do not reintroduce `insight_cards` or `evidence_chain` as project or result objects.
Traceability should be expressed through:

- `key_findings[].source_ids`
- `risks[].source_ids`

`fact_cards` may exist as intermediate search-agent output, but section saving
should not depend on `fact_ids`. Every saved section should include its referenced
`section.sources`; `save_research_section` merges those into project-level `sources`
for cross-section deduplication. Conflicts from search may exist as intermediate agent output, but they should be
written into section `risks`, usually with `risk_type = "source_conflict"`.

## Layering Rules

- Schemas live in `app/schemas/`.
- Agent orchestration lives in `app/agents/research_agent.py`.
- Agent prompts live in `app/agents/prompts/`.
- Agent-callable persistence tools live in `app/tools/research_workspace.py`.
- Deterministic report rendering lives in `app/tools/report_writer.py`.
- MongoDB access and update semantics live in `app/repository/`.
- HTTP route handlers should stay thin and delegate work to repositories/background
  tasks.

Avoid mixing schema definitions, repository writes, and agent orchestration in the
same module.

## Research Execution Rules

The manager agent should:

1. Break down section research questions.
2. Delegate evidence collection to the search subagent.
3. Write complete section bodies with the source details referenced by that section.
4. Save each section with `save_research_section`.

The search subagent should:

- collect sources,
- extract fact cards,
- identify conflicts and uncertainty,
- avoid writing final report prose,
- avoid saving database state.

The report renderer must not add facts, sources, conclusions, or risks. It only
normalizes and renders already-saved research data.

## Validation Commands

Prefer the project virtualenv:

```bash
.venv/bin/python -m pytest
.venv/bin/python -m ruff check app tests
.venv/bin/python -m py_compile app/agents/research_agent.py app/schemas/research.py
```

For targeted changes, run the smallest relevant subset first, then the full pytest
suite before handing off if feasible.

## Running Locally

Typical local API command:

```bash
.venv/bin/python -m uvicorn app.main:app --reload
```

The app serves `static/index.html` from `/` and API docs from `/api/v1/docs`.

Celery worker setup depends on Redis and the local environment configuration. Check
`.env.example`, `redis/README.md`, `mongo/README.md`, and `ragflow-docker/README.md`
when touching infrastructure.

## Coding Conventions

- Python target is 3.12.
- Ruff line length is 100.
- Use Pydantic v2 APIs such as `model_validate`, `model_dump`, and validators.
- Keep comments short and only where they clarify non-obvious behavior.
- Use `rg` for searches.
- Keep compatibility code explicit and documented.
- Do not silently drop source or fact references.
- Do not create fake URLs, dates, source titles, facts, or citations in production
  paths.

## Testing Guidance

Tests should focus on behavior:

- research material save/merge behavior,
- section validation and normalization,
- report rendering from saved research data,
- project/result assembly boundaries,
- compatibility behavior for old `key_findings` and `risks` string lists.

Avoid tests that depend on a live MongoDB, Redis, external search, or LLM unless the
test is explicitly an integration script.

## Project TODOs

- Frontend progress display: on the `static/index.html` "正在生成研究报告" waiting
  page, add a progress bar based on `completed_sections / total_sections`, where
  `total_sections` is the confirmed outline section count and `completed_sections`
  is the number of saved/generated sections.
- Research duration control: add a way to limit the total number of report sections
  so reports can finish faster. Prefer controlling this at outline generation or
  confirmation time instead of truncating already-generated research output.

## Current Caveats

- `docs/simplified_research_data_model_todo.md` tracks migration status. Check it
  before continuing the data model refactor.
- `最终课件/` still contains older teaching material that may mention
  `insight_cards` and evidence chains. Treat those files as course content requiring
  deliberate edits, not mechanical global replacement.
- The worktree may contain user or previous-agent changes. Do not revert unrelated
  changes.
