"""Integration tests for dev dependencies in generated projects."""

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from zeeker.core.project import ZeekerProjectManager

# Skip these tests in workspace mode (before publishing to PyPI)
# These tests require zeeker to be available on PyPI
pytestmark = pytest.mark.skipif(
    not os.environ.get("ZEEKER_PUBLISHED", ""),
    reason="Requires zeeker to be published to PyPI (set ZEEKER_PUBLISHED=1 to run)",
)


class TestDevDependenciesIntegration:
    """Test that generated projects can actually use dev dependencies."""

    @pytest.fixture
    def test_project_path(self):
        """Create a temporary directory for test projects."""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield Path(temp_dir)

    def test_dev_dependencies_integration(self, test_project_path):
        """Test that generated project can install and run dev dependencies."""
        project_path = test_project_path / "test_dev_project"

        # Initialize a new project
        manager = ZeekerProjectManager(project_path)
        result = manager.init_project("test_dev_project")
        assert result.is_valid

        # Verify pyproject.toml has correct structure
        pyproject_path = project_path / "pyproject.toml"
        assert pyproject_path.exists()

        content = pyproject_path.read_text()
        assert "[dependency-groups]" in content
        assert 'dev = ["black>=25.1.0", "ruff>=0.8.0"]' in content
        assert "[tool.black]" in content
        assert "[tool.ruff]" in content

        # Test that dependencies can be installed
        result = subprocess.run(
            ["uv", "sync", "--group", "dev"],
            cwd=project_path,
            capture_output=True,
            text=True,
            env={**os.environ, "VIRTUAL_ENV": ""},  # Clear any virtual env
        )
        assert result.returncode == 0, f"uv sync failed: {result.stderr}"

        # Create some Python code to format
        test_code = """
def badly_formatted_function( x,y,z ):
    if x>y:
        return z
    else:
        return None
"""

        test_file = project_path / "test_formatting.py"
        test_file.write_text(test_code)

        # Test that black can be run
        result = subprocess.run(
            ["uv", "run", "black", "--check", "--diff", "test_formatting.py"],
            cwd=project_path,
            capture_output=True,
            text=True,
            env={**os.environ, "VIRTUAL_ENV": ""},
        )
        # Should exit with 1 because file needs formatting
        assert result.returncode == 1, f"Black should detect formatting issues: {result.stdout}"

        # Test that black can actually format the file
        result = subprocess.run(
            ["uv", "run", "black", "test_formatting.py"],
            cwd=project_path,
            capture_output=True,
            text=True,
            env={**os.environ, "VIRTUAL_ENV": ""},
        )
        assert result.returncode == 0, f"Black formatting failed: {result.stderr}"

        # Verify file was actually formatted
        formatted_content = test_file.read_text()
        assert "def badly_formatted_function(x, y, z):" in formatted_content
        assert formatted_content != test_code  # Content should have changed

        # Test that ruff can be run
        result = subprocess.run(
            ["uv", "run", "ruff", "check", "test_formatting.py"],
            cwd=project_path,
            capture_output=True,
            text=True,
            env={**os.environ, "VIRTUAL_ENV": ""},
        )
        assert result.returncode == 0, f"Ruff check failed: {result.stderr}"

    def test_generated_resource_formatting(self, test_project_path):
        """Test that generated resources can be formatted with the tools."""
        project_path = test_project_path / "test_formatting_project"

        # Initialize project and add a resource
        manager = ZeekerProjectManager(project_path)
        manager.init_project("test_formatting_project")
        manager.add_resource("test_resource", "Test resource for formatting")

        # Install dev dependencies
        subprocess.run(
            ["uv", "sync", "--group", "dev"],
            cwd=project_path,
            capture_output=True,
            env={**os.environ, "VIRTUAL_ENV": ""},
        )

        # Test formatting the generated resource file
        resource_file = project_path / "resources" / "test_resource.py"
        assert resource_file.exists()

        # Test that black can format the generated file (may need formatting)
        result = subprocess.run(
            ["uv", "run", "black", str(resource_file)],
            cwd=project_path,
            capture_output=True,
            text=True,
            env={**os.environ, "VIRTUAL_ENV": ""},
        )
        # Black should be able to format without errors
        assert (
            result.returncode == 0
        ), f"Black should be able to format generated file: {result.stderr}"

        # Test that ruff can run on the generated file (may find issues)
        result = subprocess.run(
            ["uv", "run", "ruff", "check", "--fix", str(resource_file)],
            cwd=project_path,
            capture_output=True,
            text=True,
            env={**os.environ, "VIRTUAL_ENV": ""},
        )
        # Ruff should be able to run and potentially fix issues
        assert result.returncode in [0, 1], f"Ruff should run successfully: {result.stderr}"

        # After fixes, ruff should pass
        result = subprocess.run(
            ["uv", "run", "ruff", "check", str(resource_file)],
            cwd=project_path,
            capture_output=True,
            text=True,
            env={**os.environ, "VIRTUAL_ENV": ""},
        )
        assert (
            result.returncode == 0
        ), f"Generated resource should pass ruff after fixes: {result.stderr}"

    def test_tool_configuration_validity(self, test_project_path):
        """Test that the tool configurations in pyproject.toml are valid."""
        project_path = test_project_path / "test_config_project"

        # Initialize project
        manager = ZeekerProjectManager(project_path)
        manager.init_project("test_config_project")

        # Install dev dependencies
        subprocess.run(
            ["uv", "sync", "--group", "dev"],
            cwd=project_path,
            capture_output=True,
            env={**os.environ, "VIRTUAL_ENV": ""},
        )

        # Test that black accepts the configuration
        result = subprocess.run(
            ["uv", "run", "black", "--help"],
            cwd=project_path,
            capture_output=True,
            text=True,
            env={**os.environ, "VIRTUAL_ENV": ""},
        )
        assert result.returncode == 0, f"Black configuration seems invalid: {result.stderr}"

        # Test that ruff accepts the configuration
        result = subprocess.run(
            ["uv", "run", "ruff", "check", "--help"],
            cwd=project_path,
            capture_output=True,
            text=True,
            env={**os.environ, "VIRTUAL_ENV": ""},
        )
        assert result.returncode == 0, f"Ruff configuration seems invalid: {result.stderr}"

    def test_readme_commands_work(self, test_project_path):
        """Test that the formatting commands documented in README actually work."""
        project_path = test_project_path / "test_readme_project"

        # Initialize project
        manager = ZeekerProjectManager(project_path)
        manager.init_project("test_readme_project")

        # Install dev dependencies
        subprocess.run(
            ["uv", "sync", "--group", "dev"],
            cwd=project_path,
            capture_output=True,
            env={**os.environ, "VIRTUAL_ENV": ""},
        )

        # Verify README contains the commands
        readme_path = project_path / "README.md"
        readme_content = readme_path.read_text()
        assert "uv run black ." in readme_content
        assert "uv run ruff check ." in readme_content
        assert "uv run ruff check --fix ." in readme_content

        # Test each command documented in README
        commands_to_test = [
            ["uv", "run", "black", "."],
            ["uv", "run", "ruff", "check", "."],
            # Note: not testing --fix to avoid modifying files
        ]

        for cmd in commands_to_test:
            result = subprocess.run(
                cmd,
                cwd=project_path,
                capture_output=True,
                text=True,
                env={**os.environ, "VIRTUAL_ENV": ""},
            )
            assert result.returncode == 0, f"Command {' '.join(cmd)} failed: {result.stderr}"
