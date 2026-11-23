from datetime import datetime

import pytest

from poster import meta, schedule
from poster.util import VN, file_id, num, quota_day, to_dt, txt


def at(h, m=0, d=20):
    return datetime(2026, 11, d, h, m, tzinfo=VN)


# ---------- Gio_dang ----------
def test_parse_list():
    assert schedule.parse_slots("07:00,11:00, 15:00") == [420, 660, 900]


def test_parse_range_step():
    assert schedule.parse_slots("06:00-21:00/3") == [360, 540, 720, 900, 1080, 1260]


def test_parse_mixed_and_example():
    assert schedule.parse_slots("07:00-19:00/4") == [420, 660, 900, 1140]
    assert schedule.parse_slots("06:00-12:00/6, 20:30") == [360, 720, 1230]


def test_parse_blank_is_every_hour():
    assert schedule.parse_slots("") is None
    assert schedule.parse_slots(None) is None


def test_parse_accepts_seconds_from_sheet():
    assert schedule.parse_slots("7:00:00,13:00:00") == [420, 780]


@pytest.mark.parametrize("bad", ["abc", "25:00", "07:00-09:00/0", "7h"])
def test_parse_errors(bad):
    with pytest.raises(ValueError):
        schedule.parse_slots(bad)


def test_due_exact_and_late():
    slots = schedule.parse_slots("07:00,13:00")
    assert schedule.due_slot(at(7, 0), slots, 25) == at(7, 0)
    assert schedule.due_slot(at(7, 20), slots, 25) == at(7, 0)      # cron trễ 20 phút vẫn trúng
    assert schedule.due_slot(at(6, 40), slots, 25) == at(7, 0)      # chạy sớm 20 phút cũng trúng
    assert schedule.due_slot(at(8, 0), slots, 25) is None
    assert schedule.due_slot(at(7, 0), slots, 5) == at(7, 0)


def test_due_every_hour_when_blank():
    assert schedule.due_slot(at(9, 3), None, 5) == at(9, 0)
    assert schedule.due_slot(at(9, 30), None, 5) is None


def test_due_near_midnight():
    slot = schedule.due_slot(at(23, 50), [0], 25)
    assert slot == datetime(2026, 11, 21, 0, 0, tzinfo=VN)


def test_already_served():
    slot = at(10, 0)
    assert schedule.already_served([at(10, 4)], slot, 25)
    assert not schedule.already_served([at(13, 0)], slot, 25)


# ---------- ô Sheet ----------
def test_txt_num():
    assert txt(3.0) == "3" and txt(None) == "" and txt(" a ") == "a" and txt(True) == "TRUE"
    assert num("1,5") == 1.5 and num("") == 0 and num(None, 7) == 7 and num("abc", 2) == 2


def test_to_dt_string_and_serial():
    assert to_dt("2026-10-08 14:46:38") == datetime(2026, 10, 8, 14, 46, 38, tzinfo=VN)
    # 46303.5 = 2026-10-08 12:00 theo gốc ngày của Google Sheets
    assert to_dt(46303.5) == datetime(2026, 10, 8, 12, 0, tzinfo=VN)
    assert to_dt("") is None and to_dt("rác") is None


def test_file_id():
    assert file_id("https://drive.google.com/file/d/1AbC_dEf-9/view?usp=sharing") == "1AbC_dEf-9"
    assert file_id("https://drive.google.com/open?id=XYZ123") == "XYZ123"
    assert file_id("https://cdn.example.com/x.mp4") == ""


def test_quota_day_is_text_8_digits():
    q = quota_day()
    assert isinstance(q, str) and len(q) == 8 and q.isdigit()


# ---------- metadata ----------
def test_shorts_added_once():
    m = meta.finalize("Đèn LED", "Mô tả", ["a", "b"], is_short=True)
    assert m["title"].endswith("#Shorts") and m["description"].endswith("#Shorts")
    m2 = meta.finalize(m["title"], m["description"], [], is_short=True)
    assert m2["title"].count("#Shorts") == 1 and m2["description"].count("#Shorts") == 1


def test_long_video_no_shorts():
    m = meta.finalize("Tiêu đề", "Mô tả", [], is_short=False)
    assert "#Shorts" not in m["title"] + m["description"]


def test_title_100_chars_even_with_shorts():
    m = meta.finalize("x" * 300, "", [], is_short=True)
    assert len(m["title"]) <= 100 and m["title"].endswith("#Shorts")


def test_description_bytes_limit_vietnamese():
    m = meta.finalize("t", "ế" * 5000, [], is_short=False)
    assert len(m["description"].encode("utf-8")) <= 5000


def test_strip_angle_brackets():
    m = meta.finalize("a <b> c", "x > y", [], False)
    assert "<" not in m["title"] and ">" not in m["description"]


def test_tags_dedupe_and_limit():
    tags = meta.clean_tags(["Đèn LED", "đèn led", "#Shorts", "t" * 120] + [f"tag{i}" * 5 for i in range(200)])
    assert tags.count("Đèn LED") == 1 and "Shorts" in tags
    assert sum(len(t) + 1 for t in tags) <= 520
