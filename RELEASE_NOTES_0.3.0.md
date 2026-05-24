# Zeeker v0.3.0 Release Notes

## 🎉 Major Features

### 🔍 Automatic Full-Text Search for Fragments
- **Auto-FTS enabled** on all fragments tables by default
- **Smart field detection** automatically identifies text content fields (`text`, `content`, `chunk`, `fragment`, etc.)
- **Zero configuration** required - just use `--fragments` and get searchable content
- **Manual override** available with `--fragments-fts-fields` for custom field selection

### ⚡ Async Resource Support  
- **New `--async` flag** for `zeeker add` creates async-ready resource templates
- **Automatic detection** of async vs sync functions in existing resources
- **Concurrent execution** for faster data fetching from APIs and external sources
- **Backward compatible** - existing sync resources continue working unchanged

### 🎯 Selective Resource Building
- **Build specific resources** only: `zeeker build users posts` 
- **Faster development cycles** - rebuild only what changed
- **Resource filtering** works with all build options (`--sync-from-s3`, etc.)
- **Automatic dependency detection** ensures related tables are built together

### 📁 Automatic Environment Loading
- **Auto-load `.env` files** for all CLI commands (`build`, `deploy`, `assets`)
- **Zero configuration** - just create `.env` and your variables are available
- **Secure credential management** for S3, APIs, and other external services
- **Development-friendly** - no need to manually export variables

## 🔧 Enhanced Developer Experience

### 📝 Improved Documentation
- **Updated function signatures** with proper type hints and `existing_table` parameter
- **Fixed repository URLs** replacing placeholder links
- **Comprehensive examples** for both sync and async resources
- **Better CLI reference** with all new options documented

### 🗂️ Fragments Workflow Improvements
- **Enhanced context passing** eliminates duplicate API calls between `fetch_data()` and `fetch_fragments_data()`
- **Backward compatibility** maintained for resources without context parameter
- **Flexible signatures** support both old and new function patterns

### 🏗️ Better Project Scaffolding
- **PEP 621 compliant** `pyproject.toml` generation
- **Automatic dev dependencies** (black, ruff) added to new projects
- **CLAUDE.md development guide** included in all new projects
- **Improved project structure** with better defaults

## 🐛 Bug Fixes

### Database Building
- **Fixed AsyncExecutor parameter passing** that was causing CI test failures
- **Corrected fragments table creation** with proper function signature handling
- **Improved S3 sync compatibility** with boto3 client updates

### Resource Processing
- **Enhanced duplicate handling** for more reliable incremental updates
- **Better schema conflict detection** and resolution
- **Robust error handling** in fragments processing workflows

## 🔄 Breaking Changes

### Function Signatures (Documentation Fix)
- **Updated examples** now show correct `fetch_data(existing_table)` signature
- **No code changes required** - this was a documentation correction
- **Existing resources** continue working as before

### CLI Behavior
- **No breaking changes** to existing commands
- **New options added** but all existing usage patterns preserved
- **Backward compatible** with v0.2.1 projects

## 📊 New CLI Options

### Resource Creation
```bash
zeeker add resource_name --async                    # Create async resource
zeeker add docs --fragments --async                 # Async fragments resource  
zeeker add posts --fts-fields title --fts-fields content  # Custom FTS fields
```

### Building
```bash
zeeker build users posts                           # Build specific resources
zeeker build --sync-from-s3 users                 # Selective sync + build
```

## 🔍 Under the Hood

### FTS Implementation
- **FTSProcessor class** handles automatic field detection and FTS setup
- **Smart field prioritization** with common text field names
- **Integration with existing build pipeline** for seamless operation

### Async Execution
- **AsyncExecutor enhancements** for both `fetch_data` and `fetch_fragments_data`
- **Event loop management** handles nested async contexts properly
- **Thread pool fallback** for running async code in sync contexts

### Testing Improvements
- **Comprehensive test suite** for FTS functionality (9 test cases)
- **Async testing framework** for validating concurrent operations
- **Enhanced CI pipeline** with better error detection

## 🚀 Migration Guide

### From v0.2.1 to v0.3.0

1. **No action required** for existing projects - they continue working unchanged
2. **Optional**: Add `.env` file for automatic environment loading
3. **Optional**: Use `--async` flag for new API-heavy resources
4. **Optional**: Enable selective building with resource names in `zeeker build`

### Taking Advantage of New Features

1. **Enable auto-FTS**: Use `--fragments` flag (FTS is now automatic)
2. **Speed up API resources**: Add `--async` flag for concurrent fetching
3. **Faster development**: Use `zeeker build resource1 resource2` for selective builds
4. **Secure credentials**: Move API keys to `.env` file for auto-loading

## 📈 Performance Improvements

- **Faster fragments processing** with context passing (eliminates duplicate API calls)
- **Concurrent async execution** for API-heavy resources
- **Selective building** reduces build times during development
- **Better memory usage** with improved caching in AsyncExecutor

## 🔗 Links

- **GitHub Repository**: https://github.com/zeeker-sg/cli
- **Documentation**: See README.md for complete usage guide
- **Issues & Feedback**: https://github.com/zeeker-sg/cli/issues

---

**Full Changelog**: [v0.2.1...v0.3.0](https://github.com/zeeker-sg/cli/compare/v0.2.1...v0.3.0)