# Zeeker

A Python library and CLI tool for creating, managing, and deploying databases for Datasette-based systems.

## Installation

```bash
pip install zeeker
```

## Quick Start

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

## Features

- **Complete Database Projects**: Create, build, and deploy entire databases with data resources
- **Intelligent Metadata Generation**: Auto-generate column descriptions from schema analysis
- **Document Fragments**: Split large documents into searchable chunks
- **Schema Management**: Automatic versioning and conflict detection
- **S3 Deployment**: Direct deployment to S3-compatible storage
- **Full-Text Search**: Built-in FTS5 support
- **Async Support**: Concurrent data fetching for better performance

## Documentation

For full documentation, visit: https://github.com/zeeker-sg/cli

## License

MIT License - see LICENSE file for details
