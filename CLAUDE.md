# AMStock Project Environment

## Python environment

Always use `uv run python` to run any Python script or command in this project. `uv run` ensures the correct virtual environment and `PYTHONPATH` are set up so the `amstock` module can be imported.

**Preferred:**
```
uv run python path/to/script.py
uv run python -c "import amstock; ..."
```

**Avoid** bare `python` — it may not find the `amstock` module.

## Project layout

- Source package: `src/amstock/`
- Skill scripts: `skills/<skill-name>/scripts/`
- Tests: `tests/`
