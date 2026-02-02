# Gemini Contribution Guide

This document provides guidelines for Gemini when contributing to this project.

## Python Style Guide

For Python code, strictly follow the [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html).

Key points to remember:

- **Indentation:** Use 4 spaces for indentation.
- **Imports:** Import standard modules first, then third-party modules, then local application imports. Sort alphabetically within each group.
- **Naming:**
  - `module_name`, `package_name`, `method_name`, `function_name`, `instance_var_name`, `function_parameter_name`, `local_var_name`
  - `ClassName`, `ExceptionName`
  - `GLOBAL_CONSTANT_NAME`
- **Docstrings:** Use Google-style docstrings.
- **Typing:** Use type hints for function arguments and return values.
- **Ordering:** Sort functions by usage (top to bottom), so the code reads like a story (entry point first, then helpers).

## Project Specifics

_(This section will be updated with project-specific details as they are discovered during our conversations.)_

- **Project Root:** `/home/vladimir-minev/Documents/workspace/clipper`
- **Source Code:** `src/` directory.
- **Tests:** Test files are located next to the file being tested, with a `_test.py` suffix (e.g., `src/utils_test.py`).
- **Dependency Management:** `pyproject.toml` (using `uv`).
- **Linting & Formatting:** `ruff` is used for linting.
- **Type Checking:** `ty` is used for type checking.
- **Test Runner:** `pytest` is used for running tests.
- **Environment Variables:** `GEMINI_API_KEY` is required for some functionality (e.g., `src/uploader.py`).
- **Credentials:** Google OAuth credentials are expected at `src/google_auth.CREDENTIALS_PATH`.

## Notes

- Always check `pyproject.toml` for the latest dependencies and tool configurations.
- Verify changes with `ruff check .` and `ty check .` before considering a task complete.
- Run tests using `PYTHONPATH=. uv run pytest` (or appropriate command if environment changes).
