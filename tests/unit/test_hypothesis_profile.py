from hypothesis import settings


def test_hypothesis_has_no_deadline_for_the_whole_suite() -> None:
    assert settings().deadline is None
