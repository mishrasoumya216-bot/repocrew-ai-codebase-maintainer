"""Test suite for the miniutils package (RepoCrew sample repo).

Happy paths are covered; the tests that expose the three seeded bugs fail
intentionally so that RepoCrew's Tester has a real, verifiable signal:
  - test_average_empty_list_returns_zero  (issue #1)
  - test_paginate_last_partial_page       (issue #2)
  - test_slugify_strips_trailing_hyphen   (issue #3)
"""

import pytest

from miniutils import average, paginate, slugify


def test_average_basic():
    assert average([1.0, 2.0, 3.0]) == 2.0


def test_average_single_value():
    assert average([4]) == 4.0


def test_average_empty_list_returns_zero():
    assert average([]) == 0.0


def test_paginate_even_split():
    assert paginate([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]


def test_paginate_last_partial_page():
    assert paginate([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]


def test_paginate_empty():
    assert paginate([], 3) == []


def test_paginate_invalid_page_size():
    with pytest.raises(ValueError):
        paginate([1, 2, 3], 0)


def test_slugify_basic():
    assert slugify("Hello World") == "hello-world"


def test_slugify_collapses_separators():
    assert slugify("a  b---c") == "a-b-c"


def test_slugify_strips_trailing_hyphen():
    assert slugify("Hello, World!") == "hello-world"
