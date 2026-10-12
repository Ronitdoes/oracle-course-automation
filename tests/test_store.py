"""Finished-section memory: what the course walk already completed."""
from storage.run_store import RunStore, course_key_for_url


def test_course_key_stable_across_session_rotation():
    a = course_key_for_url("https://academy.oracle.com/pls/f?p=63000:14:111:::14:P14_ID,P14_COURSE_ID:60388,62&cs=AAA")
    b = course_key_for_url("https://academy.oracle.com/pls/f?p=63000:14:222:::14:P14_ID:60388&cs=BBB")
    assert a == b == "60388"


def test_course_key_different_courses_differ():
    a = course_key_for_url("https://x/pls/f?p=1:14:::14:P14_ID:111&cs=1")
    b = course_key_for_url("https://x/pls/f?p=1:14:::14:P14_ID:222&cs=2")
    assert a != b


def test_course_key_falls_back_to_plain_address(tmp_path):
    url = "file:///D:/course/journey.html#outline"
    assert course_key_for_url(url) == "file:///D:/course/journey.html"
    assert course_key_for_url("") == ""


def test_finished_sections_roundtrip(tmp_path):
    store = RunStore(str(tmp_path / "runs.sqlite"))
    assert store.finished_sections("60388") == {}
    store.record_finished_section("60388", "Section 8 - Using and Managing Procedures")
    got = store.finished_sections("60388")
    assert set(got) == {"Section 8 - Using and Managing Procedures"}
    assert got["Section 8 - Using and Managing Procedures"] > 0
    # Other courses are separate buckets.
    assert store.finished_sections("99999") == {}
    # Re-recording updates the timestamp instead of duplicating.
    before = got["Section 8 - Using and Managing Procedures"]
    store.record_finished_section("60388", "Section 8 - Using and Managing Procedures")
    assert store.finished_sections("60388")["Section 8 - Using and Managing Procedures"] >= before
    # Empty keys never stored.
    store.record_finished_section("", "Section 8")
    store.record_finished_section("60388", "")
    assert set(store.finished_sections("60388")) == {"Section 8 - Using and Managing Procedures"}
