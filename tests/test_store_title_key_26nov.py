"""26 Nov: the Exam Study Planner was created on Payhip but reported 'not created' (the list shortens long titles), and
the same raw compare guarded against double listings."""
from engine import store_publish as sp


def test_shortened_store_titles_still_match():
    full = "Exam Study Planner Printable | Board Exam, JEE, NEET, UPSC Revision Timetable & Syllabus Tracker PDF"
    assert sp._title_key("Exam Study Planner Printable | Board Exam, JEE, ...") == sp._title_key(full)
    assert sp._title_key("Weekly Meal Planner Printable | Grocery List") != sp._title_key(full)
