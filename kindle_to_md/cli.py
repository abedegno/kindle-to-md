"""CLI entry point for kindle-to-md."""

import sys
from pathlib import Path

import click

from kindle_to_md.browser import BrowserDriver
from kindle_to_md.extractor import extract_book
from kindle_to_md.markdown import count_existing_pages


@click.command()
@click.argument("asin")
@click.option("-o", "--output", default=None, help="Output file path (default: {ASIN}.md)")
@click.option("-b", "--backend", default="lightpanda", type=click.Choice(["lightpanda", "chromium"]), help="Browser backend")
@click.option("--region", default="co.uk", help="Amazon region (co.uk, com, de, etc.)")
@click.option("--timeout", default=300, help="Auth timeout in seconds")
@click.option("--delay", default=1.0, help="Delay between page turns in seconds")
@click.option("--reauth", is_flag=True, help="Force fresh login")
@click.option("--resume", is_flag=True, help="Resume from existing partial output")
def main(asin: str, output: str, backend: str, region: str, timeout: int, delay: float, reauth: bool, resume: bool):
    """Extract a Kindle ebook to Markdown.

    ASIN is the Amazon book identifier (e.g., B0G6MF376S).
    You can also pass a full Kindle URL — the ASIN will be extracted.
    """
    # Extract ASIN from URL if needed
    if "asin=" in asin:
        asin = asin.split("asin=")[1].split("&")[0]
    elif "/" in asin:
        # Try to find ASIN-like pattern
        parts = asin.split("/")
        for part in parts:
            if part.startswith("B0") and len(part) == 10:
                asin = part
                break

    output_path = Path(output) if output else Path(f"{asin}.md")
    images_dir = output_path.parent / "images"

    driver = BrowserDriver(
        backend=backend,
        region=region,
    )

    try:
        # Handle auth
        session_file = driver._session_file()
        if reauth or not session_file.exists():
            print("Login required. Opening browser...", file=sys.stderr)
            driver.login(timeout=timeout)
            # Re-create driver for extraction
            driver = BrowserDriver(backend=backend, region=region)

        # Determine resume point
        resume_from = 0
        if resume and output_path.exists():
            resume_from = count_existing_pages(str(output_path))
            print(f"Resuming from page {resume_from}...", file=sys.stderr)
        elif not resume and output_path.exists():
            # Start fresh
            output_path.unlink()

        # Launch extraction browser
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
        if backend == "lightpanda":
            print("Tip: try --backend chromium if Lightpanda isn't working.", file=sys.stderr)
        sys.exit(1)
    finally:
        driver.shutdown()
