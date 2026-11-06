"""Item-81 spec validator tests."""
from research.spec import check, render, REQUIRED, E8_EXAMPLE


def test_complete_spec_passes():
    ok, missing = check(dict(E8_EXAMPLE))
    assert ok is True and missing == []
    text = render(dict(E8_EXAMPLE))
    assert 'E8-CONVEXIT' in text and 'COMPLETE' in text


def test_incomplete_fails_with_fields():
    spec = {'id': 'X', 'version': 'v1'}
    ok, missing = check(spec)
    assert ok is False
    assert 'hypothesis' in missing and 'stop_criteria' in missing
    assert 'INCOMPLETE' in render(spec)


def test_not_a_dict():
    ok, missing = check(None)
    assert ok is False and missing == list(REQUIRED)


def test_example_covers_all_fields():
    for field in REQUIRED:
        assert E8_EXAMPLE[field], field
