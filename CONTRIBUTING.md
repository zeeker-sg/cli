# Contributing to Zeeker

Thank you for your interest in contributing to Zeeker! This guide will help you get started with development in the workspace architecture.

## Table of Contents

- [Workspace Structure](#workspace-structure)
- [Development Setup](#development-setup)
- [Development Workflow](#development-workflow)
- [Testing](#testing)
- [Code Style](#code-style)
- [Making Changes](#making-changes)
- [Publishing (Maintainers)](#publishing-maintainers)

## Workspace Structure

Zeeker is organized as a **uv workspace** with multiple packages:

```
zeeker/
├── packages/
│   ├── zeeker/              # Core framework
│   │   ├── zeeker/          # Source code
│   │   ├── tests/           # Tests
│   │   └── pyproject.toml   # Package config
│   │
│   └── zeeker-common/       # Shared utilities
│       ├── zeeker_common/   # Source code
│       ├── tests/           # Tests (optional)
│       └── pyproject.toml   # Package config
│
├── examples/                # Example projects
│   ├── legal-news/          # Advanced example
│   └── datasets/            # Simple example
│
├── .github/workflows/       # CI/CD
│   ├── test.yml             # Test all packages
│   ├── publish-zeeker.yml   # Publish zeeker
│   └── publish-common.yml   # Publish zeeker-common
│
├── pyproject.toml           # Workspace configuration
├── pytest.ini               # Test configuration
└── README.md                # Main documentation
```

## Development Setup

### Prerequisites

- Python 3.12 or higher
- [uv](https://docs.astral.sh/uv/) - Fast Python package manager

### Initial Setup

1. Fork the repository on GitHub

2. Clone your fork:
   ```bash
   git clone https://github.com/YOUR_USERNAME/zeeker.git
   cd zeeker
   ```

3. Install uv if you haven't already:
   ```bash
   # On macOS/Linux
   curl -LsSf https://astral.sh/uv/install.sh | sh

   # On Windows
   powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```

4. Install all workspace dependencies:
   ```bash
   uv sync
   ```

   This creates a unified `.venv` at the workspace root and installs all packages in editable mode.

## Development Workflow

### Running Tests

```bash
# Run all tests across all packages
uv run pytest

# Run specific package tests
uv run pytest packages/zeeker/tests
uv run pytest packages/zeeker-common/tests

# Run with specific markers
uv run pytest -m unit
uv run pytest -m integration
uv run pytest -m "not slow"

# Run with coverage
uv run pytest --cov
```

### Code Formatting

We use **Black** for code formatting:

```bash
# Check formatting
uv run black --check .

# Apply formatting
uv run black .
```

### Linting

We use **Ruff** for linting:

```bash
# Check for issues
uv run ruff check .

# Auto-fix issues
uv run ruff check --fix .
```

### Testing the CLI

The CLI is available via `uv run`:

```bash
# Test CLI
uv run zeeker --help

# Test project creation
uv run zeeker init test-project
cd test-project
uv run zeeker add test-resource
uv run zeeker build
```

## Testing

### Test Organization

Tests are organized by package:

- `packages/zeeker/tests/` - Core framework tests
- `packages/zeeker-common/tests/` - Utilities tests (if needed)

### Test Markers

We use pytest markers to categorize tests:

- `@pytest.mark.unit` - Unit tests
- `@pytest.mark.integration` - Integration tests
- `@pytest.mark.cli` - CLI interface tests
- `@pytest.mark.slow` - Tests that take longer to run

Example:
```python
import pytest

@pytest.mark.unit
def test_project_manager():
    # Test code here
    pass
```

### Running Specific Tests

```bash
# Run only unit tests
uv run pytest -m unit

# Run only fast tests
uv run pytest -m "not slow"

# Run a specific test file
uv run pytest packages/zeeker/tests/test_project.py

# Run a specific test
uv run pytest packages/zeeker/tests/test_project.py::test_specific_function
```

## Code Style

### Python Style Guide

- **Line length**: 100 characters
- **String quotes**: Double quotes preferred
- **Imports**: Organized with `ruff` (E, F, W, I)
- **Type hints**: Use where it improves clarity

### Docstring Style

Use Google-style docstrings:

```python
def fetch_data(existing_table: Optional[Table]) -> List[Dict[str, Any]]:
    """Fetch data for the resource.

    Args:
        existing_table: sqlite-utils Table object or None

    Returns:
        List of dictionaries containing data to insert

    Raises:
        ValueError: If data validation fails
    """
    pass
```

## Making Changes

### Workflow

1. Create a feature branch:
   ```bash
   git checkout -b feature/my-feature
   ```

2. Make your changes in the appropriate package:
   - Core framework changes → `packages/zeeker/zeeker/`
   - Utility changes → `packages/zeeker-common/zeeker_common/`
   - Tests → `packages/*/tests/`

3. Add tests for your changes

4. Run the test suite:
   ```bash
   uv run pytest
   ```

5. Format and lint your code:
   ```bash
   uv run black .
   uv run ruff check --fix .
   ```

6. Commit your changes:
   ```bash
   git add .
   git commit -m "Add feature: description of your changes"
   ```

7. Push to your fork:
   ```bash
   git push origin feature/my-feature
   ```

8. Create a Pull Request on GitHub

### Commit Messages

Use clear, descriptive commit messages:

- **Good**: "Add async support for resource fetching"
- **Good**: "Fix schema conflict detection for JSON columns"
- **Bad**: "Fix bug"
- **Bad**: "Update code"

### Pull Request Guidelines

- **Title**: Clear description of what the PR does
- **Description**: Explain why the change is needed and how it works
- **Tests**: Include tests for new functionality
- **Documentation**: Update relevant documentation
- **Small PRs**: Keep PRs focused on a single feature or fix

## Working with Packages

### Adding Dependencies

**To core zeeker package:**
```bash
cd packages/zeeker
uv add package-name
```

**To zeeker-common:**
```bash
cd packages/zeeker-common
uv add package-name
```

**To workspace dev dependencies:**
Edit root `pyproject.toml`:
```toml
[tool.uv]
dev-dependencies = [
    "pytest>=8.4.0",
    "new-package>=1.0.0",
]
```

Then run `uv sync`.

### Testing Package Interactions

Since all packages are installed in editable mode, changes are immediately reflected:

```python
# In packages/zeeker-common/zeeker_common/utils.py
def new_utility():
    return "test"

# In packages/zeeker/zeeker/core/project.py
from zeeker_common import new_utility  # Works immediately!
```

### Running Example Projects

Test your changes with the example projects:

```bash
cd examples/legal-news
uv sync  # Sync within example
uv run zeeker build
```

## Publishing (Maintainers)

Releases are built and uploaded by `.github/workflows/publish-zeeker.yml`
using PyPI Trusted Publishing (OIDC). There is no PyPI token to manage and
nothing is published from a laptop.

Before anything is uploaded the workflow:

1. runs the full test suite (`test.yml`, reused via `workflow_call`);
2. checks that the version in the package's `pyproject.toml` equals the
   version named by the release tag (or the manual `version` input);
3. for releases, checks that the tagged commit is on `main`;
4. checks that this version is not already on PyPI (releases are immutable).

The `release` environment only accepts deployments from `main` and from
`v*` tags, and requires a maintainer approval before the publish job runs.

### Releasing zeeker

Tags are `vX.Y.Z` and carry the zeeker version.

1. Bump `version` in `packages/zeeker/pyproject.toml` on a branch, run
   `uv lock`, and merge the PR to `main` (CI must pass).
2. Tag the merge commit on `main` and push the tag:
   ```bash
   git checkout main && git pull
   git tag v0.9.1
   git push origin v0.9.1
   ```
3. Create a GitHub Release for that tag (Releases → Draft a new release →
   choose the tag → "Generate release notes" → Publish). Publishing the
   release triggers the workflow.
4. Approve the `release` environment deployment when GitHub asks, then
   confirm the new version appears at https://pypi.org/project/zeeker/.

zeeker is pre-1.0, so a minor bump (0.8 → 0.9) may be breaking. Call out
anything consumers must change in the release notes: every data project
in the org pins zeeker in its `uv.lock` and only picks the release up when
that lock is bumped, so the release notes are what they read first.

### Releasing zeeker-common

zeeker-common has no release tag. Bump `version` in
`packages/zeeker-common/pyproject.toml`, merge to `main`, then run
**Actions → Publish zeeker to PyPI → Run workflow** from `main` with
`package = zeeker-common` and `version` set to the new version. The
workflow refuses to run if the input and `pyproject.toml` disagree.

### If a publish fails

Fix the cause on `main`, then re-run the workflow manually with the same
`package` and `version`. Do not retag; the version check will still pass
because nothing reached PyPI. If a broken build *did* reach PyPI, yank it
on PyPI and release a new patch version.

## Questions?

- **Issues**: https://github.com/zeeker-sg/cli/issues
- **Discussions**: https://github.com/zeeker-sg/cli/discussions
- **Email**: houfu@outlook.sg

## Code of Conduct

Be respectful and constructive in all interactions. We're all here to build something useful together.

---

Thank you for contributing to Zeeker! 🚀
