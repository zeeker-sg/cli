"""
Zeeker - Database customization tool with project management capabilities.

A tool for creating, validating, and deploying database customizations
for Zeeker's Datasette-based system using sqlite-utils and following
the three-pass asset system.
"""

from .core import (
    DatabaseCustomization,
    DeploymentChanges,
    Skip,
    ValidationResult,
    ZeekerDeployer,
    ZeekerGenerator,
    ZeekerProject,
    ZeekerProjectManager,
    ZeekerValidator,
)

__version__ = "0.9.0"
__all__ = [
    "Skip",
    "ValidationResult",
    "DatabaseCustomization",
    "DeploymentChanges",
    "ZeekerProject",
    "ZeekerProjectManager",
    "ZeekerValidator",
    "ZeekerGenerator",
    "ZeekerDeployer",
]
