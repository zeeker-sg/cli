# Migration Guide: Zeeker 0.5.x → 0.6.0

## Overview

Zeeker 0.6.0 introduces a workspace architecture that separates the core framework from shared utilities and example projects. While the architecture has changed significantly for development, **the user-facing CLI remains backward compatible**.

## For End Users (CLI Users)

### TL;DR

If you only use the CLI, update your existing projects with these simple changes:

```toml
# In your project's pyproject.toml
dependencies = [
    "zeeker>=0.6.0",
]
```

Then run:
```bash
cd your-project
uv sync
```

That's it! Your workflow remains exactly the same.

### Detailed Migration Steps

#### 1. Update Project Dependencies

**Old** (`pyproject.toml`):
```toml
dependencies = ["zeeker"]
```

**New** (`pyproject.toml`):
```toml
dependencies = [
    "zeeker>=0.6.0",
]

# Optional: Add zeeker-common for utilities
# dependencies = [
#     "zeeker>=0.6.0",
#     "zeeker-common>=0.1.0",
# ]
```

#### 2. (Optional) Use zeeker-common Utilities

If you were copy-pasting helper functions from examples, you can now use zeeker-common:

**Before** (copying code):
```python
# You had to copy-paste these functions into your resources
import hashlib

def get_hash_id(elements):
    return hashlib.md5("|".join(str(e) for e in elements).encode()).hexdigest()
```

**After** (using zeeker-common):
```bash
# Install the utilities package
uv add zeeker-common
```

```python
# Import from zeeker-common
from zeeker_common import get_hash_id, get_jina_reader_content, async_retry
```

**Available utilities in zeeker-common:**
- `get_hash_id(elements)` - Generate deterministic hash IDs
- `get_jina_reader_content(url)` - Extract web content with Jina Reader
- `async_retry` - Retry decorator for async functions
- `get_summary(text)` - OpenAI summarization (requires `zeeker-common[openai]`)

#### 3. Update Environment Setup

Nothing changes! Your `.env` file and environment variables work exactly the same:

```bash
# S3 deployment
S3_BUCKET=your-bucket
AWS_ACCESS_KEY_ID=your-key
AWS_SECRET_ACCESS_KEY=your-secret

# API keys
JINA_API_TOKEN=your-token
OPENAI_API_KEY=your-key
```

### What Stays the Same

✅ All CLI commands work identically:
- `zeeker init` - Create projects
- `zeeker add` - Add resources
- `zeeker build` - Build databases
- `zeeker deploy` - Deploy to S3
- `zeeker assets` - Manage UI assets
- `zeeker metadata` - Generate metadata

✅ Resource files (`resources/*.py`) work the same

✅ Project structure remains unchanged

✅ Generated projects have the same structure

✅ Deployment workflows are identical

## For Library Users

If you imported zeeker as a Python library:

### Import Changes

**Most imports still work** with backward compatibility:

```python
# These still work
from zeeker import ZeekerProjectManager
from zeeker import ZeekerDeployer, ZeekerValidator
```

**Recommended new imports:**
```python
# More explicit (optional, but recommended)
from zeeker.core import ZeekerProjectManager
from zeeker.core import ZeekerDeployer, ZeekerValidator
```

### Deprecation Warnings

If you were using utility functions that have moved to zeeker-common, you'll see deprecation warnings:

```python
# This will work but show a deprecation warning
from zeeker import get_hash_id  # Deprecated

# Do this instead
pip install zeeker-common
from zeeker_common import get_hash_id
```

## For Contributors

### Repository Structure Changes

**Before (0.5.x):**
```
zeeker/
├── zeeker/           # Package code
├── tests/            # Tests
└── pyproject.toml    # Single package
```

**After (0.6.0):**
```
zeeker/
├── packages/
│   ├── zeeker/       # Core package
│   └── zeeker-common/ # Utilities
├── examples/         # Example projects
└── pyproject.toml    # Workspace config
```

### Development Workflow Changes

**Old workflow:**
```bash
git clone https://github.com/zeeker-sg/cli.git
cd zeeker
uv sync
uv run pytest
```

**New workflow (exactly the same!):**
```bash
git clone https://github.com/zeeker-sg/cli.git
cd zeeker
uv sync
uv run pytest
```

The commands are identical! The workspace is transparent to developers.

### Testing Changes

Tests are now organized by package:

```bash
# Run all tests
uv run pytest

# Run specific package tests
uv run pytest packages/zeeker/tests
uv run pytest packages/zeeker-common/tests

# Run with markers (unchanged)
uv run pytest -m unit
uv run pytest -m integration
```

## Breaking Changes

### None for CLI Users!

The CLI is fully backward compatible. Existing projects work without modification (except updating the dependency version).

### Minor Breaking Changes for Library Users

1. **Utility functions moved**: If you imported utility functions directly from `zeeker`, install `zeeker-common` and import from there instead.

2. **Import paths**: Some internal import paths changed, but public API remains stable. If you were importing from `zeeker.core.*` directly, those paths are unchanged.

## New Features in 0.6.0

### 1. zeeker-common Package

A new package with reusable utilities for data projects:

```bash
pip install zeeker-common
```

Includes:
- Hash ID generation
- Jina Reader integration
- Retry decorators
- OpenAI integration (optional)

### 2. Example Projects

Two reference implementations in the repository:

- `examples/legal-news/` - Advanced example with async fetching and zeeker-common
- `examples/datasets/` - Simple example with static data

### 3. Improved Project Templates

Generated projects now include:
- Updated dependency specifications (`zeeker>=0.6.0`)
- Comments showing zeeker-common usage
- Better examples and documentation

### 4. Workspace Development

For contributors, the workspace architecture enables:
- Unified dependency management
- Parallel development on packages
- Shared example projects
- Better code organization

## Troubleshooting

### "Module 'zeeker' has no attribute 'get_hash_id'"

**Solution**: Install zeeker-common

```bash
uv add zeeker-common
```

```python
from zeeker_common import get_hash_id
```

### Tests failing after upgrade

**Solution**: Make sure you're in the repository root and run:

```bash
uv sync
uv run pytest
```

### Import errors in existing projects

**Solution**: Update your project dependencies:

```bash
cd your-project
uv sync
```

## Questions?

- **Documentation**: See [README.md](README.md) for workspace overview
- **Examples**: Check `examples/` directory for reference implementations
- **Issues**: Report issues at https://github.com/zeeker-sg/cli/issues

## Summary

**For most users**: Update `pyproject.toml` dependency to `zeeker>=0.6.0` and run `uv sync`. Everything else works the same.

**For advanced users**: Consider using `zeeker-common` for shared utilities instead of copy-pasting code.

**For contributors**: The workspace is transparent - development workflow is unchanged.
