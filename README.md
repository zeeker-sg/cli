# Zeeker Workspace

[![PyPI version](https://badge.fury.io/py/zeeker.svg)](https://badge.fury.io/py/zeeker)
[![Test Status](https://github.com/zeeker-sg/cli/workflows/Test/badge.svg)](https://github.com/zeeker-sg/cli/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

A Python library and CLI tool for creating, managing, and deploying databases for Datasette-based systems.

## Workspace Structure

This repository is organized as a **uv workspace** containing:

- **`packages/zeeker/`** - Core Zeeker package (published to PyPI)
- **`packages/zeeker-common/`** - Common utilities for data projects (published to PyPI)
- **`packages/zeeker-datasette/`** - Datasette deployment package with custom templates and plugins
- **`examples/`** - Example data projects demonstrating best practices

## For Users

### Installation

```bash
pip install zeeker

# Optional: Install common utilities
pip install zeeker-common
```

### Quick Start

```bash
# Create a new database project
zeeker init my-project
cd my-project

# Add a data resource
zeeker add users --description "User data"

# Edit resources/users.py to implement fetch_data()

# Build the database
zeeker build

# Deploy to S3 (optional)
zeeker deploy
```

### Documentation

For full documentation, see:
- [Zeeker Package README](packages/zeeker/README.md) - Core package documentation
- [Zeeker-Common Package README](packages/zeeker-common/README.md) - Utilities documentation
- [Zeeker-Datasette Package README](packages/zeeker-datasette/Readme.md) - Deployment package documentation
- [Migration Guide](MIGRATION-0.6.md) - Upgrading from v0.5.x
- [Examples](examples/) - Reference implementations

## For Contributors

### Development Setup

1. Install uv: https://docs.astral.sh/uv/
2. Clone repository:
   ```bash
   git clone https://github.com/zeeker-sg/cli.git
   cd zeeker
   ```
3. Install all workspace dependencies:
   ```bash
   uv sync
   ```

### Development Workflow

```bash
# Run all tests
uv run pytest

# Run specific package tests
uv run pytest packages/zeeker/tests
uv run pytest packages/zeeker-common/tests
uv run pytest packages/zeeker-datasette/tests

# Run formatting and linting
uv run black .
uv run ruff check .

# Test the CLI
uv run zeeker --help
```

### Repository Structure

```
zeeker/
├── packages/
│   ├── zeeker/              # Core package
│   │   ├── zeeker/          # Source code
│   │   ├── tests/           # Tests
│   │   ├── pyproject.toml   # Package config
│   │   └── README.md        # Package docs
│   │
│   ├── zeeker-common/       # Utilities package
│   │   ├── zeeker_common/   # Source code
│   │   ├── tests/           # Tests
│   │   ├── pyproject.toml   # Package config
│   │   └── README.md        # Package docs
│   │
│   └── zeeker-datasette/    # Datasette deployment
│       ├── plugins/         # Custom Datasette plugins
│       ├── templates/       # Jinja templates
│       ├── static/          # CSS, JS, images
│       ├── scripts/         # Deployment scripts
│       ├── tests/           # Tests
│       ├── Dockerfile       # Container image
│       ├── pyproject.toml   # Package config
│       └── README.md        # Package docs
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
├── pyproject.toml           # Workspace config
├── pytest.ini               # Test config
└── README.md                # This file
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed contribution guidelines.

## Features

- **Complete Database Projects**: Create, build, and deploy entire databases with data resources
- **Intelligent Metadata Generation**: Auto-generate column descriptions from schema analysis
- **Document Fragments**: Split large documents into searchable chunks
- **Schema Management**: Automatic versioning and conflict detection
- **S3 Deployment**: Direct deployment to S3-compatible storage
- **Full-Text Search**: Built-in FTS5 support
- **Async Support**: Concurrent data fetching for better performance
- **Shared Utilities**: Reusable code in zeeker-common package

## What's New in v0.6.0

- **🔧 Workspace Architecture**: Refactored into uv workspace with separate packages
- **📦 PyPI Distribution**: Core package available on PyPI
- **🛠️ Shared Utilities**: New zeeker-common package with reusable utilities
- **📚 Example Projects**: Reference implementations for learning best practices
- **🔄 Unified Dependencies**: Single lock file for all workspace members

## License

MIT License - see LICENSE file for details

## Links

- [PyPI: zeeker](https://pypi.org/project/zeeker/)
- [PyPI: zeeker-common](https://pypi.org/project/zeeker-common/)
- [GitHub Repository](https://github.com/zeeker-sg/cli)
- [Issue Tracker](https://github.com/zeeker-sg/cli/issues)
