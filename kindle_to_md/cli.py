"""CLI entry point for kindle-to-md."""

import logging
import sys
from pathlib import Path

import click

from kindle_to_md.browser import BrowserDriver
from kindle_to_md.extractor import extract_book
from kindle_to_md.markdown import count_existing_pages


def resolve_project_dir(asin: str, base: Path = Path(".")) -> Path:
    """Create and return the project directory for a book."""
    project_dir = base / "projects" / asin
    (project_dir / "images").mkdir(parents=True, exist_ok=True)
    return project_dir


@click.command()
@click.argument("asin", required=False)
@click.option("-o", "--output", default=None, help="Output file path (default: projects/{ASIN}/book.md)")
@click.option("--region", default="co.uk", help="Amazon region (co.uk, com, de, etc.)")
@click.option("--timeout", default=300, help="Auth timeout in seconds")
@click.option("--delay", default=1.0, help="Delay between page turns in seconds")
@click.option("--login", is_flag=True, help="Open browser for Amazon login, then exit")
@click.option("--reauth", is_flag=True, help="Force fresh login")
@click.option("--resume", is_flag=True, help="Resume from existing partial output")
@click.option("--reprocess", is_flag=True, help="Re-run OCR on cached screenshots (no browser needed)")
@click.option("--ocr", default="tesseract", type=click.Choice(["tesseract", "mlx"]), help="OCR engine (mlx uses Qwen2.5-VL)")
@click.option("--headed", is_flag=True, help="Run browser in headed mode (visible window)")
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose logging")
def main(asin, output, region, timeout, delay, login, reauth, resume, reprocess, ocr, headed, verbose):
    """Extract a Kindle ebook to Markdown.

    ASIN is the Amazon book identifier (e.g., B0G6MF376S).
    You can also pass a full Kindle URL — the ASIN will be extracted.
    """
    log_level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stderr,
    )

    # Login-only mode
    if login:
        driver = BrowserDriver(region=region, headed=True)
        try:
            driver.login(timeout=timeout)
            print("Session saved. You can now extract books.", file=sys.stderr)
        finally:
            driver.shutdown()
        return

    # ASIN is required for all other modes
    if not asin:
        raise click.UsageError("ASIN is required (or use --login)")

    # Extract ASIN from URL if needed
    if "asin=" in asin:
        asin = asin.split("asin=")[1].split("&")[0]
    elif "/" in asin:
        parts = asin.split("/")
        for part in parts:
            if part.startswith("B0") and len(part) == 10:
                asin = part
                break

    project_dir = resolve_project_dir(asin)
    images_dir = project_dir / "images"
    output_path = Path(output) if output else project_dir / "book.md"

    # Re-process mode: re-run OCR on cached screenshots
    if reprocess:
        _reprocess_screenshots(images_dir, output_path, ocr)
        return

    driver = BrowserDriver(region=region, headed=headed)

    try:
        # Handle auth
        session_file = driver._session_file()
        if reauth or not session_file.exists():
            print("Login required. Opening browser...", file=sys.stderr)
            driver.login(timeout=timeout)
            driver = BrowserDriver(region=region, headed=headed)

        # Determine resume point
        resume_from = 0
        if resume and output_path.exists():
            resume_from = count_existing_pages(str(output_path))
            print(f"Resuming from page {resume_from}...", file=sys.stderr)
        elif not resume and output_path.exists():
            output_path.unlink()

        page = driver.launch()

        extract_book(
            page=page,
            asin=asin,
            region=region,
            output_path=output_path,
            images_dir=images_dir,
            delay=delay,
            resume_from=resume_from,
        )

        print(f"\nOutput saved to {output_path}", file=sys.stderr)

    except KeyboardInterrupt:
        print("\n\nInterrupted. Partial output saved.", file=sys.stderr)
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        driver.shutdown()


def _reprocess_screenshots(images_dir: Path, output_path: Path, engine: str = "tesseract") -> None:
    """Re-run OCR and formatting on cached screenshots without a browser."""
    from kindle_to_md.ocr import ocr_screenshot
    from kindle_to_md.extractor import PageContent
    from kindle_to_md.markdown import format_page, append_page

    pages = sorted(images_dir.glob("page-*.png"))
    if not pages:
        print(f"No screenshots found in {images_dir}", file=sys.stderr)
        sys.exit(1)

    output_path.unlink(missing_ok=True)

    print(f"Re-processing {len(pages)} screenshots with {engine}...", file=sys.stderr)
    prev_text = ""
    for i, img_path in enumerate(pages):
        page_num = int(img_path.stem.split("-")[1])
        screenshot_bytes = img_path.read_bytes()

        if engine == "mlx":
            from kindle_to_md.ocr import ocr_screenshot as _ocr
            text = _ocr(screenshot_bytes, engine="mlx")
        else:
            text = ocr_screenshot(screenshot_bytes, engine="tesseract")

        content = PageContent(
            text=text,
            images=[f"images/{img_path.name}"],
            chapter_heading=None,
            page_number=page_num,
        )

        if engine == "mlx":
            from kindle_to_md.markdown import append_page as _ap, PAGE_MARKER
            parts = [text]
            parts.append(PAGE_MARKER.format(page_number=content.page_number))
            _ap(output_path, "\n\n".join(parts))
        else:
            formatted = format_page(content, prev_text)
            append_page(output_path, formatted)

        prev_text = content.text.strip()

        if (i + 1) % 10 == 0 or (i + 1) == len(pages):
            print(f"\r{i + 1}/{len(pages)}", end="", file=sys.stderr)

    print(f"\nOutput saved to {output_path}", file=sys.stderr)
