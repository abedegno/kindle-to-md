import pytest
from kindle_to_md.extractor import PageContent, extract_page_content


def test_page_content_dataclass():
    """PageContent should hold text, images, and chapter info."""
    pc = PageContent(text="Hello", images=[], chapter_heading=None, page_number=1)
    assert pc.text == "Hello"
    assert pc.page_number == 1


def test_has_meaningful_text():
    """PageContent with 20+ chars should be considered meaningful."""
    pc = PageContent(text="This is meaningful text content", images=[], chapter_heading=None, page_number=1)
    assert pc.has_meaningful_text()

    sparse = PageContent(text="Short", images=[], chapter_heading=None, page_number=1)
    assert not sparse.has_meaningful_text()
