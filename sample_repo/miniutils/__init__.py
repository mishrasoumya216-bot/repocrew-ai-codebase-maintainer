"""miniutils: a tiny utility library used by the RepoCrew demo."""

import re


def average(nums):
    """Return the arithmetic mean of a non-empty list of numbers."""
    return sum(nums) / len(nums)


def paginate(items, page_size):
    """Split items into pages of at most page_size elements."""
    if page_size <= 0:
        raise ValueError("page_size must be positive")
    return [items[i:i + page_size] for i in range(0, len(items) - page_size + 1, page_size)]


def slugify(text):
    """Convert text into a URL-friendly slug."""
    text = text.strip().lower()
    return re.sub(r"[^a-z0-9]+", "-", text)


__all__ = ["average", "paginate", "slugify"]
