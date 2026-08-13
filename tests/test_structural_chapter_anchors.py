from __future__ import annotations

from app.pipeline.structural import structural_cleanup


def test_referenced_chapter_fragment_binds_to_matching_h1_ordinal() -> None:
    markdown = (
        "# One\n\n"
        "[Go to two](#chapter-02)\n\n"
        "# Two\n\n"
        "# Three\n"
    )

    assert structural_cleanup(markdown) == (
        "# One\n\n"
        "[Go to two](#chapter-02)\n\n"
        "# Two {#chapter-02}\n\n"
        "# Three\n"
    )


def test_existing_or_unsafe_chapter_bindings_are_not_rewritten() -> None:
    existing_target = (
        "# One\n\n"
        "[Go to two](#chapter-02)\n\n"
        "[Existing target]{#chapter-02}\n\n"
        "# Two\n"
    )
    explicit_heading = (
        "# One\n\n"
        "[Go to two](#chapter-02)\n\n"
        "# Two {#different}\n"
    )
    out_of_range = "# One\n\n[Missing](#chapter-03)\n\n# Two\n"
    ambiguous = (
        "# One\n\n"
        "[Two](#chapter-02) [Also two](#chapter-002)\n\n"
        "# Two\n"
    )

    assert structural_cleanup(existing_target) == existing_target
    assert structural_cleanup(explicit_heading) == explicit_heading
    assert structural_cleanup(out_of_range) == out_of_range
    assert structural_cleanup(ambiguous) == ambiguous


def test_fenced_headings_and_links_do_not_affect_chapter_ordinals() -> None:
    markdown = (
        "# One\n\n"
        "````text\n"
        "# Not a chapter\n"
        "[Not navigation](#chapter-03)\n"
        "```\n"
        "still fenced\n"
        "````\n\n"
        "[Go to two](#chapter-02)\n\n"
        "# Two\n"
    )

    assert structural_cleanup(markdown) == (
        "# One\n\n"
        "````text\n"
        "# Not a chapter\n"
        "[Not navigation](#chapter-03)\n"
        "```\n"
        "still fenced\n"
        "````\n\n"
        "[Go to two](#chapter-02)\n\n"
        "# Two {#chapter-02}\n"
    )
