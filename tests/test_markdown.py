from pathlib import Path
from kindle_to_md.markdown import remove_overlap, format_page, append_page, count_existing_pages
from kindle_to_md.extractor import PageContent


def test_remove_overlap_detects_matching_suffix_prefix():
    prev = "Line 1\nLine 2\nLine 3\nLine 4"
    curr = "Line 3\nLine 4\nLine 5\nLine 6"
    result = remove_overlap(prev, curr)
    assert "Line 3" not in result
    assert "Line 4" not in result
    assert "Line 5" in result
    assert "Line 6" in result


def test_remove_overlap_no_overlap():
    prev = "AAA\nBBB"
    curr = "CCC\nDDD"
    result = remove_overlap(prev, curr)
    assert result == "CCC\nDDD"


def test_format_page_with_chapter():
    pc = PageContent(
        text="Some content here.",
        images=["images/img-001.png"],
        chapter_heading="Chapter 1",
        page_number=1,
    )
    result = format_page(pc, prev_text="")
    assert "## Chapter 1" in result
    assert "Some content here." in result
    assert "![](images/img-001.png)" in result
    assert "<!-- page:1 -->" in result


def test_format_page_no_chapter():
    pc = PageContent(
        text="Just text.",
        images=[],
        chapter_heading=None,
        page_number=2,
    )
    result = format_page(pc, prev_text="")
    assert "Just text." in result
    assert "##" not in result
    assert "<!-- page:2 -->" in result


def test_append_and_count_pages(tmp_path):
    """append_page writes to file, count_existing_pages reads page markers."""
    output = tmp_path / "test.md"
    pc1 = PageContent(text="Page one content.", images=[], chapter_heading=None, page_number=1)
    pc2 = PageContent(text="Page two content.", images=[], chapter_heading=None, page_number=2)

    append_page(output, format_page(pc1, prev_text=""))
    append_page(output, format_page(pc2, prev_text="Page one content."))

    assert count_existing_pages(str(output)) == 2
