"""Portable, self-contained BacktestWitness evidence reports."""
from .renderer import render_report, write_gallery, write_report
from .failure_renderer import render_failure_report, write_failure_gallery, write_failure_report

__all__ = ["render_report", "write_report", "write_gallery", "render_failure_report", "write_failure_report", "write_failure_gallery"]
