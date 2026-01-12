"""
Lyra Report Generation Module.

This module provides tools for generating reports and visualizations
from Lyra's evidence graph database.
"""

from src.report.dashboard import DashboardConfig, generate_dashboard

__all__ = ["generate_dashboard", "DashboardConfig"]
