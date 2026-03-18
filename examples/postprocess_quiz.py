#!/usr/bin/env python3
"""Example post-processor for quiz/exam practice books.

Usage:
    python examples/postprocess_quiz.py projects/B0G6MF376S/book.md output_clean.md

This script normalises formatting for books with Question/Answer/Explanation
structure. Adapt it for your own book formats.
"""

import re
import sys
from pathlib import Path


def postprocess(text: str) -> str:
    """Normalise Qwen markdown output for consistent formatting."""

    # 1. Remove page-break separators (---) that split sentences/paragraphs.
    #    A real section break has blank lines on both sides AND the next line
    #    starts a new structural element (heading, question, answer key, etc).
    #    A spurious break sits between continuation text.
    lines = text.split("\n")
    cleaned = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip() == "---":
            # Look ahead: is the next non-blank line a continuation of prose?
            next_content = ""
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j < len(lines):
                next_content = lines[j].strip()

            # Keep separator only before structural elements
            is_structural = bool(
                re.match(r"^#{1,3}\s", next_content)
                or re.match(r"^\*{0,2}Question\s+\d+", next_content, re.IGNORECASE)
                or re.match(r"^Question\s+\d+", next_content, re.IGNORECASE)
                or re.match(r"^\|", next_content)  # table
                or re.match(r"^#.*Answer Key", next_content, re.IGNORECASE)
                or next_content == ""  # end of file
            )

            if is_structural:
                cleaned.append(line)
            else:
                # Spurious break — replace with blank line to join paragraphs
                if cleaned and cleaned[-1].strip() != "":
                    cleaned.append("")
            i += 1
        else:
            cleaned.append(line)
            i += 1

    text = "\n".join(cleaned)

    # 2. Normalise question headings to ### Question N:
    #    Matches: # Question N:, ## Question N:, **Question N:**, **Question N:**
    text = re.sub(
        r"^#{1,6}\s+\*{0,2}(Question\s+\d+[:.])\*{0,2}",
        r"### \1",
        text,
        flags=re.MULTILINE,
    )
    # Bare **Question N:** or bold question at start of line
    text = re.sub(
        r"^\*{2}(Question\s+\d+[:.]\*{2})",
        lambda m: "### " + m.group(1).replace("**", ""),
        text,
        flags=re.MULTILINE,
    )
    text = re.sub(
        r"^\*{2}(Question\s+\d+[:.])\*{2}\s*",
        r"### \1 ",
        text,
        flags=re.MULTILINE,
    )
    # Bare "Question N:" at start of line (no markdown)
    text = re.sub(
        r"^(Question\s+\d+[:.])\s",
        r"### \1 ",
        text,
        flags=re.MULTILINE,
    )

    # 2b. Normalise answer options (A-F) to one per line, no blank lines between.
    #     Case 1: bunched on one line — "A) foo B) bar C) baz"
    #     Split before each B)-F) that follows text
    text = re.sub(
        r"(?<=[^\n])[ \t]+([B-F]\)[ \t])",
        r"\n\1",
        text,
    )
    #     Case 2: blank lines between options — collapse to single newlines
    #     Match a block of options with blank lines between them
    def collapse_option_blanks(m):
        block = m.group(0)
        # Remove blank lines between option lines
        lines = block.split("\n")
        result = []
        for line in lines:
            if line.strip() == "" and result and re.match(r"^[A-F]\)", result[-1]):
                continue  # skip blank line between options
            result.append(line)
        return "\n".join(result)

    # Find blocks that start with A) and contain B)-F) with optional blank lines between
    text = re.sub(
        r"^((?:\*\*)?[A-F]\).*\n)(?:\n*(?:\*\*)?[A-F]\).*\n?)+",
        collapse_option_blanks,
        text,
        flags=re.MULTILINE,
    )

    # Add trailing backslash to each option line for markdown line breaks
    text = re.sub(
        r"^([A-F]\).*[^\\])$",
        r"\1\\",
        text,
        flags=re.MULTILINE,
    )

    # 2c. Demote headings on non-structural lines (Correct Answer, Explanation, etc.)
    #      Must run before answer/explanation normalisation so they match.
    text = re.sub(
        r"^#{1,6}\s+(Correct Answer:)",
        r"\1",
        text,
        flags=re.MULTILINE,
    )
    text = re.sub(
        r"^#{1,6}\s+(Explanation:)",
        r"\1",
        text,
        flags=re.MULTILINE,
    )

    # 3. Normalise "Correct Answer" lines
    #    Target: **Correct Answer: X**  (bold the whole thing)
    #    Handles: **Correct Answer:** A, **Correct Answer: A**, Correct Answer: A
    text = re.sub(
        r"^\*{2}Correct Answer:\*{2}\s*([A-F])\s*$",
        r"**Correct Answer: \1**",
        text,
        flags=re.MULTILINE,
    )
    text = re.sub(
        r"^\*{2}Correct Answer:\s*([A-F])\*{2}\s*$",
        r"**Correct Answer: \1**",
        text,
        flags=re.MULTILINE,
    )
    text = re.sub(
        r"^Correct Answer:\s*([A-F])\s*$",
        r"**Correct Answer: \1**",
        text,
        flags=re.MULTILINE,
    )
    # Also catch any remaining bare "Correct Answer: X" mid-line won't happen,
    # but handle the case where trailing space prevents match
    text = re.sub(
        r"^Correct Answer:\s+([A-F])[ \t]*$",
        r"**Correct Answer: \1**",
        text,
        flags=re.MULTILINE,
    )

    # 4. Normalise "Explanation:" lines
    #    Target: **Explanation:** (bold label, then text follows)
    #    First: heading-style explanations
    text = re.sub(
        r"^#{1,6}\s+Explanation:\s*",
        "\n**Explanation:** ",
        text,
        flags=re.MULTILINE,
    )
    # Standalone bold or bare "Explanation:" at start of line
    text = re.sub(
        r"^\*{2}Explanation:\*{2}\s*",
        "**Explanation:** ",
        text,
        flags=re.MULTILINE,
    )
    text = re.sub(
        r"^Explanation:\s*",
        "**Explanation:** ",
        text,
        flags=re.MULTILINE,
    )

    # 4b. Ensure Correct Answer and Explanation are on separate lines
    text = re.sub(
        r"(\*\*Correct Answer: [A-F]\*\*)\s*(\*\*Explanation:\*\*)",
        r"\1\n\n\2",
        text,
    )

    # 5. Remove spurious headings that are actually continuation text
    #    e.g. "# Performance Metrics for Specific Rules in Elastic SIEM"
    #    that should just be paragraph text (not preceded by Question pattern)
    def demote_spurious_heading(m):
        heading_text = m.group(1).strip()
        # Keep legitimate headings
        if re.match(r"Question\s+\d+", heading_text, re.IGNORECASE):
            return m.group(0)
        if re.match(r"(Practice Questions|About This Book|Quick Answer Key|Elastic Certified)", heading_text, re.IGNORECASE):
            return m.group(0)
        # Demote to plain text
        return heading_text

    text = re.sub(
        r"^#{1,2}\s+(.+)$",
        demote_spurious_heading,
        text,
        flags=re.MULTILINE,
    )

    # 6. Rebuild the Quick Answer Key table from extracted answers.
    #    The original table is often broken across page boundaries.
    #    Extract all answers from the document and regenerate cleanly.
    answers = re.findall(r"\*\*Correct Answer: ([A-F])\*\*", text)

    # Remove all existing answer key content (everything from first "Quick Answer Key" to end)
    text = re.sub(
        r"\n*#{0,3}\s*Quick Answer Key.*",
        "",
        text,
        flags=re.DOTALL,
    )

    # Rebuild the table if we found answers
    if answers:
        table_lines = [
            "\n---\n",
            "### Quick Answer Key\n",
            "| # | Answer | # | Answer | # | Answer | # | Answer | # | Answer |",
            "|---|--------|---|--------|---|--------|---|--------|---|--------|",
        ]
        # 5-column layout for compactness
        cols = 5
        rows = (len(answers) + cols - 1) // cols
        for row in range(rows):
            cells = []
            for col in range(cols):
                idx = col * rows + row
                if idx < len(answers):
                    cells.append(f"| {idx + 1} | {answers[idx]} ")
                else:
                    cells.append("|   |   ")
            table_lines.append("".join(cells) + "|")
        text = text.rstrip() + "\n" + "\n".join(table_lines) + "\n"

    # 7. Ensure consistent --- separator before every ### Question heading
    #    First remove any existing --- before questions (to avoid doubles)
    text = re.sub(r"\n---\n+(?=### Question)", "\n", text)
    #    Then add --- before every ### Question
    text = re.sub(r"\n(?=### Question)", "\n\n---\n\n", text)

    # 8. Collapse double --- separators
    text = re.sub(r"---\n+---", "---", text)

    # 9. Collapse multiple blank lines to max 2
    text = re.sub(r"\n{4,}", "\n\n\n", text)

    # 8. Remove trailing whitespace
    text = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)

    return text.strip() + "\n"


def main():
    if len(sys.argv) < 2:
        print("Usage: postprocess.py <input.md> [output.md]", file=sys.stderr)
        sys.exit(1)

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else input_path.with_stem(input_path.stem + "_clean")

    text = input_path.read_text()
    result = postprocess(text)
    output_path.write_text(result)
    print(f"Processed: {input_path} -> {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
