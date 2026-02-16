"""Rich-based logging setup for the pipeline."""

from __future__ import annotations

import logging

from rich.console import Console
from rich.logging import RichHandler

console = Console()


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure rich logging for the application."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(message)s",
        datefmt="[%X]",
        handlers=[
            RichHandler(
                console=console,
                rich_tracebacks=True,
                show_path=False,
            )
        ],
    )
    logger = logging.getLogger("meta_ads")
    return logger


def get_logger(name: str = "meta_ads") -> logging.Logger:
    return logging.getLogger(name)
