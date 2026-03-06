"""
Legacy import path.

The old `gui.projects_tab` module has been renamed to `gui.deep_research_tab` to reflect its purpose:
Deep Research (research artifacts + final research brief), not Workspace collaborative drafting.
"""

from gui.deep_research_tab import (  # noqa: F401
    DeepResearchTab,
    ProjectsTab,
    _format_artifact_for_display,
)

