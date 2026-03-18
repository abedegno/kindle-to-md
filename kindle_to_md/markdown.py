"""Markdown formatting and assembly for extracted Kindle content."""

import re
from pathlib import Path

from kindle_to_md.extractor import PageContent

# Page marker used for resume counting
PAGE_MARKER = "<!-- page:{page_number} -->"


def remove_overlap(prev_text: str, current_text: str) -> str:
    """Remove overlapping text between consecutive pages."""
    prev_lines = prev_text.strip().split("\n")
    curr_lines = current_text.strip().split("\n")

    if not prev_lines or not curr_lines:
        return current_text

    max_check = min(10, len(prev_lines), len(curr_lines))
    best_overlap = 0

    for overlap_size in range(1, max_check + 1):
        prev_suffix = [l.strip() for l in prev_lines[-overlap_size:]]
        curr_prefix = [l.strip() for l in curr_lines[:overlap_size]]
        if prev_suffix == curr_prefix:
            best_overlap = overlap_size

    if best_overlap > 0:
        return "\n".join(curr_lines[best_overlap:])
    return current_text


def format_page(content: PageContent, prev_text: str) -> str:
    """Format a single page's content as Markdown with dedup against previous page."""
    parts = []

    if content.chapter_heading:
        parts.append(f"\n## {content.chapter_heading}\n")

    text = content.text.strip()
    if prev_text:
        text = remove_overlap(prev_text, text)

    if text:
        text = _add_headings(text)
        parts.append(text)

    for img_path in content.images:
        parts.append(f"\n![]({img_path})\n")

    # Add page marker for resume support
    parts.append(PAGE_MARKER.format(page_number=content.page_number))

    return "\n\n".join(parts)


def _add_headings(text: str) -> str:
    """Detect heading-like lines in OCR text and format as Markdown headings.

    Conservative approach: only format lines that are clearly structural
    (question numbers, correct answers, explanations). Avoids false positives
    from answer choices like "A) True" or short content lines.
    """
    lines = text.split("\n")
    result = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            result.append(line)
            continue

        is_heading = False

        # Pattern: "Question N:" or "Question N." at start of line
        if re.match(r"^Question\s+\d+[\s:.]", stripped):
            result.append(f"\n### {stripped}")
            is_heading = True
        # Pattern: "Correct Answer:" line
        elif stripped.startswith("Correct Answer:"):
            result.append(f"\n**{stripped}**")
            is_heading = True
        # Pattern: "Explanation:" at start
        elif stripped.startswith("Explanation:"):
            result.append(f"\n**Explanation:** {stripped[12:].strip()}")
            is_heading = True

        if not is_heading:
            result.append(line)

    return "\n".join(result)


def append_page(output_path: Path, formatted_text: str) -> None:
    """Append a formatted page to the output file."""
    with open(output_path, "a", encoding="utf-8") as f:
        f.write(formatted_text)
        f.write("\n\n")


def count_existing_pages(output_path: str) -> int:
    """Count pages in an existing partial output file for resume support.

    Uses page markers (<!-- page:N -->) for accurate counting.
    """
    p = Path(output_path)
    if not p.exists():
        return 0
    content = p.read_text(encoding="utf-8")
    import re
    markers = re.findall(r"<!-- page:(\d+) -->", content)
    if markers:
        return int(markers[-1])  # Return the last page number
    return 0
