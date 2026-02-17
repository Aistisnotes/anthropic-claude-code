"""Report output generation - saves reports to files and prints summaries."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from meta_ads_analyzer.models import PatternReport
from meta_ads_analyzer.utils.logging import get_logger

logger = get_logger(__name__)


class ReportWriter:
    """Write pattern analysis reports to disk."""

    def __init__(self, config: dict[str, Any]):
        r_cfg = config.get("reporting", {})
        self.output_dir = Path(r_cfg.get("output_dir", "output/reports"))
        self.format = r_cfg.get("format", "markdown")
        self.include_raw = r_cfg.get("include_raw_data", False)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def save_report(self, report: PatternReport, run_id: str) -> Path:
        """Save the pattern report to disk.

        Returns path to the saved report file.
        """
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        safe_query = "".join(
            c if c.isalnum() or c in "-_ " else "" for c in report.search_query
        )[:50].strip().replace(" ", "_")

        if self.format == "markdown":
            return self._save_markdown(report, run_id, timestamp, safe_query)
        elif self.format == "json":
            return self._save_json(report, run_id, timestamp, safe_query)
        elif self.format == "html":
            return self._save_html(report, run_id, timestamp, safe_query)
        else:
            return self._save_markdown(report, run_id, timestamp, safe_query)

    def _save_markdown(
        self, report: PatternReport, run_id: str, timestamp: str, safe_query: str
    ) -> Path:
        path = self.output_dir / f"{timestamp}_{safe_query}_{run_id}.md"
        path.write_text(report.full_report_markdown, encoding="utf-8")
        logger.info(f"Report saved: {path}")
        return path

    def _save_json(
        self, report: PatternReport, run_id: str, timestamp: str, safe_query: str
    ) -> Path:
        path = self.output_dir / f"{timestamp}_{safe_query}_{run_id}.json"
        data = report.model_dump(mode="json")
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        logger.info(f"Report saved: {path}")
        return path

    def _save_html(
        self, report: PatternReport, run_id: str, timestamp: str, safe_query: str
    ) -> Path:
        """Convert markdown to basic HTML."""
        path = self.output_dir / f"{timestamp}_{safe_query}_{run_id}.html"

        # Simple markdown to HTML (for full conversion, use a proper library)
        md = report.full_report_markdown
        html_content = _simple_md_to_html(md)

        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Ad Analysis Report - {report.search_query}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
               max-width: 900px; margin: 0 auto; padding: 2rem; line-height: 1.6; }}
        table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
        th, td {{ border: 1px solid #ddd; padding: 0.5rem; text-align: left; }}
        th {{ background: #f5f5f5; }}
        h1 {{ color: #1a1a1a; }}
        h2 {{ color: #333; border-bottom: 2px solid #eee; padding-bottom: 0.5rem; }}
        h3 {{ color: #555; }}
        hr {{ border: none; border-top: 2px solid #eee; margin: 2rem 0; }}
        .quality-pass {{ color: #22c55e; font-weight: bold; }}
        .quality-fail {{ color: #ef4444; font-weight: bold; }}
    </style>
</head>
<body>
{html_content}
</body>
</html>"""
        path.write_text(html, encoding="utf-8")
        logger.info(f"Report saved: {path}")
        return path


def _simple_md_to_html(md: str) -> str:
    """Bare-bones markdown to HTML conversion."""
    import re

    lines = md.split("\n")
    html_lines = []
    in_table = False
    in_list = False

    for line in lines:
        # Headers
        if line.startswith("### "):
            html_lines.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith("## "):
            html_lines.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("# "):
            html_lines.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("---"):
            html_lines.append("<hr>")
        elif line.startswith("|"):
            if not in_table:
                html_lines.append("<table>")
                in_table = True
            if line.startswith("|---") or line.startswith("| ---"):
                continue
            cells = [c.strip() for c in line.split("|")[1:-1]]
            tag = "th" if not any("<tr>" in l for l in html_lines[-5:]) else "td"
            row = "".join(f"<{tag}>{c}</{tag}>" for c in cells)
            html_lines.append(f"<tr>{row}</tr>")
        elif line.startswith("- "):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line[2:])
            html_lines.append(f"<li>{content}</li>")
        elif re.match(r"^\d+\. ", line):
            content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
            content = re.sub(r"^\d+\. ", "", content)
            html_lines.append(f"<p>{content}</p>")
        elif line.strip() == "":
            if in_table:
                html_lines.append("</table>")
                in_table = False
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append("")
        else:
            content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
            html_lines.append(f"<p>{content}</p>")

    if in_table:
        html_lines.append("</table>")
    if in_list:
        html_lines.append("</ul>")

    return "\n".join(html_lines)
