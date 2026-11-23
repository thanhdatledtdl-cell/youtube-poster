from datetime import datetime, timedelta

import pytest

from poster import gemini
from poster.gemini import GeminiError, GeminiPool, _BadOutput, _KeyFail
from poster.runner import Runner
from poster.util import VN, fmt_dt
from poster.youtube import QuotaError
from tests.fakes import make_book, video

NOW = datetime(2026, 11, 20, 10, 5, tzinfo=VN)   # trong khung 10:00 của T_NGAN


def make_runner(book, tmp_path, **kw):
    r = Runner(book, creds=None, workdir=str(tmp_path), now_fn=lambda: NOW, **kw)
    r.calls = {"upload": 0, "download": 0, "gemini": 0}

    def make_yt(api):
        return object()

    def download(fid, dest):
        r.calls["download"] += 1
        open(dest, "wb").write(b"\x00\x00\x00 ftypmp42" + b"0" * 100)
        return 120

    def upload(yt, path, m, category, privacy):
        r.calls["upload"] += 1
        r.last = dict(m=m, category=category, privacy=privacy)
        return "VID" + str(r.calls["upload"])

    def gen_json(model, prompt):
        r.calls["gemini"] += 1
        r.last_prompt = prompt
        return {"title": "Tiêu đề AI", "description": "Mô tả AI", "tags": ["đèn", "led"]}

    r.make_yt, r.download, r.upload, r.gen_json = make_yt, download, upload, gen_json
    return r


def test_dry_run_changes_nothing(tmp_path):
    book = make_book([video()])
    before = [list(x) for x in book.t["Kenh_T_Ngan"]], [list(x) for x in book.t["THEO_DOI"]]
    r = make_runner(book, tmp_path, dry_run=True)
    r.run()
    assert (book.t["Kenh_T_Ngan"], book.t["THEO_DOI"]) == before
    assert r.calls == {"upload": 0, "download": 0, "gemini": 0}
    assert r.results[0]["status"] == "XEM THỬ"


def test_happy_path_writes_everything(tmp_path):
    book = make_book([video(title="Đèn pha 200W")])
    r = make_runner(book, tmp_path, privacy="private")
    r.run()

    row = book.row("Kenh_T_Ngan", 2)
    assert row["Trang_thai_dang"] == "Done"
    assert row["Link_Youtube_video"] == "https://www.youtube.com/watch?v=VID1"
    assert row["Thoi_gian_dang_video"] == fmt_dt(NOW)
    assert row["Tieu_de_youtube"].endswith("#Shorts")            # Loai = Ngan
    assert row["Mo_ta_youtube"].endswith("#Shorts")
    assert row["The_tag"] == "đèn, led"
    assert row["Loi"] == "" and row["Lock_time"] == ""
    assert r.last["privacy"] == "private" and r.last["category"] == 26   # ép private, bỏ qua 'public' của CONFIG
    assert "Đèn pha 200W" in r.last_prompt and "Kenh_T" in r.last_prompt  # biến {{...}} được thay

    log = book.t["THEO_DOI"][-1]
    h = book.t["THEO_DOI"][0]
    d = dict(zip(h, log))
    assert d["Ket_qua"] == "Done" and d["ID"] == "T_NGAN" and d["Kenh"] == "Kenh_T" and d["Loai"] == "Ngan"
    assert d["Quota_cost"] == 1600.0 and d["Du_an"] == "PROJECT_1" and d["API_name"] == "YT_T"
    assert isinstance(d["Ngay_quota"], str) and len(d["Ngay_quota"]) == 8     # TEXT yyyymmdd
    assert d["Link"].endswith("VID1")


def test_existing_metadata_skips_gemini(tmp_path):
    book = make_book([video(Tieu_de_youtube="Tiêu đề sẵn", Mo_ta_youtube="Mô tả sẵn", The_tag="a, b")])
    r = make_runner(book, tmp_path, force=True)
    r.run()
    assert r.calls["gemini"] == 0 and r.calls["upload"] == 1
    assert book.row("Kenh_T_Ngan", 2)["Tieu_de_youtube"].startswith("Tiêu đề sẵn")


def test_only_empty_fields_are_filled(tmp_path):
    book = make_book([video(Tieu_de_youtube="Giữ nguyên tiêu đề")])
    r = make_runner(book, tmp_path, force=True)
    r.run()
    row = book.row("Kenh_T_Ngan", 2)
    assert row["Tieu_de_youtube"].startswith("Giữ nguyên tiêu đề")
    assert row["Mo_ta_youtube"].startswith("Mô tả AI")


def test_not_due_is_skipped_unless_forced(tmp_path):
    book = make_book([video()])
    r = Runner(book, workdir=str(tmp_path), now_fn=lambda: datetime(2026, 11, 20, 12, 0, tzinfo=VN))
    r.run()
    assert r.results[0]["status"] == "CHƯA ĐẾN GIỜ"
    assert book.row("Kenh_T_Ngan", 2)["Trang_thai_dang"] == "Cho_dang"


def test_late_cron_within_tolerance_posts(tmp_path):
    book = make_book([video()])
    r = make_runner(book, tmp_path)
    r.now_fn = lambda: datetime(2026, 11, 20, 10, 22, tzinfo=VN)   # trễ 22 phút, dung sai 25
    r.run()
    assert r.calls["upload"] == 1


def test_no_double_post_in_same_slot(tmp_path):
    book = make_book([video(fid="A1"), video(title="V2", fid="B2")])
    r = make_runner(book, tmp_path)
    r.run()
    r2 = make_runner(book, tmp_path)       # bấm chạy lần 2 cùng khung giờ
    r2.run()
    assert r.calls["upload"] == 1 and r2.calls["upload"] == 0
    assert "đã đăng cho khung giờ" in r2.results[0]["msg"]
    assert book.row("Kenh_T_Ngan", 3)["Trang_thai_dang"] == "Cho_dang"


def test_inactive_skipped_but_explicit_pipeline_runs(tmp_path):
    book = make_book([video()])
    book.t["CONFIG"][1][4] = False
    r = make_runner(book, tmp_path, force=True)
    r.run()
    assert r.calls["upload"] == 0
    r2 = make_runner(book, tmp_path, force=True, only=["T_NGAN"])
    r2.run()
    assert r2.calls["upload"] == 1


def test_videos_posted_top_to_bottom_and_limited_by_so_video(tmp_path):
    book = make_book([video(title="Một", fid="A1"), video(title="Hai", fid="B2")])
    r = make_runner(book, tmp_path, force=True)
    r.run()
    assert book.row("Kenh_T_Ngan", 2)["Trang_thai_dang"] == "Done"
    assert book.row("Kenh_T_Ngan", 3)["Trang_thai_dang"] == "Cho_dang"


def test_quota_limits_videos(tmp_path):
    book = make_book([video()], quota_left=1000)   # < 1600
    r = make_runner(book, tmp_path, force=True)
    r.run()
    assert r.calls["upload"] == 0 and r.results[0]["status"] == "HẾT QUOTA"


def test_max_videos_override(tmp_path):
    book = make_book([video(fid="A1"), video(title="V2", fid="B2")])
    book.t["CONFIG"][1][6] = 5.0
    r = make_runner(book, tmp_path, force=True, max_videos=2)
    r.run()
    assert r.calls["upload"] == 2


# ---------- lỗi ----------
def test_upload_failure_retries_then_marks_loi(tmp_path):
    book = make_book([video()])

    def boom(*a, **k):
        raise RuntimeError("boom 500")

    for attempt in (1, 2, 3):
        r = make_runner(book, tmp_path, force=True)
        r.upload = boom
        r.run()
        row = book.row("Kenh_T_Ngan", 2)
        assert row["So_lan_thu"] == attempt
        assert "boom 500" in row["Loi"] and "[upload]" in row["Loi"]
        assert row["Trang_thai_dang"] == ("Loi" if attempt == 3 else "Cho_dang")
        assert row["Lock_time"] == ""
    # THEO_DOI ghi 3 dòng Loi, tốn quota vì lỗi ở bước upload
    errs = [dict(zip(book.t["THEO_DOI"][0], x)) for x in book.t["THEO_DOI"][2:]]
    assert len(errs) == 3 and all(e["Ket_qua"] == "Loi" and e["Quota_cost"] == 1600 for e in errs)


def test_download_failure_costs_no_quota(tmp_path):
    book = make_book([video()])
    r = make_runner(book, tmp_path, force=True)

    def bad(fid, dest):
        raise RuntimeError("Drive hết lượt tải")

    r.download = bad
    r.run()
    d = dict(zip(book.t["THEO_DOI"][0], book.t["THEO_DOI"][-1]))
    assert d["Ket_qua"] == "Loi" and d["Quota_cost"] == 0 and "[tải Drive]" in d["Loi"]
    assert r.calls["upload"] == 0


def test_quota_error_releases_row_without_counting_attempt(tmp_path):
    book = make_book([video()])
    r = make_runner(book, tmp_path, force=True)

    def quota(*a, **k):
        raise QuotaError("quotaExceeded")

    r.upload = quota
    r.run()
    row = book.row("Kenh_T_Ngan", 2)
    assert row["Trang_thai_dang"] == "Cho_dang" and row["So_lan_thu"] in ("", 0, None)
    assert row["Lock_time"] == "" and r.results[-1]["status"] == "HẾT QUOTA"
    assert len(book.t["THEO_DOI"]) == 2          # không ghi nhật ký giả


def test_gemini_failure_marks_attempt(tmp_path):
    book = make_book([video()])
    r = make_runner(book, tmp_path, force=True)

    def bad(model, prompt):
        raise GeminiError("Không còn key")

    r.gen_json = bad
    r.run()
    row = book.row("Kenh_T_Ngan", 2)
    assert row["So_lan_thu"] == 1 and "[gemini]" in row["Loi"]


def test_missing_prompt_is_clear_error(tmp_path):
    book = make_book([video()])
    book.t["CONFIG"][1][10] = "Prompt_Khong_Co"
    r = make_runner(book, tmp_path, force=True)
    r.run()
    assert "Thiếu prompt" in book.row("Kenh_T_Ngan", 2)["Loi"]


def test_bad_drive_link_is_error_not_crash(tmp_path):
    book = make_book([video()])
    book.t["Kenh_T_Ngan"][1][1] = "https://cdn.example.com/x.mp4"
    r = make_runner(book, tmp_path, force=True)
    r.run()
    assert "ID file Drive" in book.row("Kenh_T_Ngan", 2)["Loi"]


# ---------- khóa dòng ----------
def test_fresh_lock_is_not_touched_but_stale_lock_is_retried(tmp_path):
    fresh = fmt_dt(NOW - timedelta(minutes=5))
    stale = fmt_dt(NOW - timedelta(minutes=45))
    book = make_book([video(fid="A1", status="Dang_xu_ly", Lock_time=fresh),
                      video(title="Kẹt", fid="B2", status="Dang_xu_ly", Lock_time=stale)])
    book.t["CONFIG"][1][6] = 2.0
    r = make_runner(book, tmp_path, force=True)
    r.run()
    assert book.row("Kenh_T_Ngan", 2)["Trang_thai_dang"] == "Dang_xu_ly"     # đang chạy ở nơi khác
    done = book.row("Kenh_T_Ngan", 3)
    assert done["Trang_thai_dang"] == "Done" and done["So_lan_thu"] == 1      # kẹt -> tính 1 lần thử


def test_row_found_again_after_rows_shift(tmp_path):
    book = make_book([video(title="Cần đăng", fid="A1")])
    r = make_runner(book, tmp_path, force=True)
    orig_upload = r.upload

    def upload_then_shift(*a, **k):
        # trong lúc upload, ai đó chèn 1 dòng lên đầu tab
        book.t["Kenh_T_Ngan"].insert(1, video(title="Chèn", fid="ZZZ", status="Nhap"))
        return orig_upload(*a, **k)

    r.upload = upload_then_shift
    r.run()
    assert book.row("Kenh_T_Ngan", 3)["Trang_thai_dang"] == "Done"           # ghi đúng dòng mới của nó
    assert book.row("Kenh_T_Ngan", 2)["Trang_thai_dang"] == "Nhap"


def test_auth_error_does_not_burn_attempts(tmp_path):
    from poster.youtube import AuthError
    book = make_book([video()])
    r = make_runner(book, tmp_path, force=True)

    def bad_auth(api):
        raise AuthError("invalid_grant")

    r.make_yt = bad_auth
    r.run()
    row = book.row("Kenh_T_Ngan", 2)
    assert row["Trang_thai_dang"] == "Cho_dang" and row["So_lan_thu"] in ("", 0, None)
    assert r.results[-1]["status"] == "LỖI TOKEN"


def test_other_pipelines_survive_one_failure(tmp_path):
    book = make_book([video()])
    book.t["CONFIG"].insert(1, ["X_DAI", "Kenh_X", "Dai", "Tab_Khong_Co", True, "", 1.0, "public", 26.0, "YT_T", "Prompt_Ngan"])
    r = make_runner(book, tmp_path, force=True)
    r.run()
    statuses = {x["id"]: x["status"] for x in r.results}
    assert statuses["X_DAI"] == "LỖI" and statuses["T_NGAN"] == "XONG"


# ---------- Gemini: xoay key ----------
def pool(book):
    return GeminiPool(book, so_key_thu=3, max_loi_key=3)


def test_gemini_picks_least_used_key_and_counts(tmp_path, monkeypatch):
    book = make_book([video()])
    used = []

    def fake_call(model, key, prompt):
        used.append(key)
        return {"title": "t", "description": "d", "tags": []}

    monkeypatch.setattr(GeminiPool, "_call", staticmethod(fake_call))
    pool(book).generate_json("m", "p")
    assert used == ["AIzaB"]                                   # KEY02 dùng ít hơn (1 < 5)
    k2 = dict(zip(book.t["GEMINI_KEYS"][0], book.t["GEMINI_KEYS"][2]))
    assert k2["Da_dung_hom_nay"] == 2 and k2["So_loi_lien_tiep"] == 0 and k2["Cap_nhat_luc"]


def test_gemini_falls_back_to_next_key_and_marks_errors(monkeypatch):
    book = make_book([video()])

    def fake_call(model, key, prompt):
        if key == "AIzaB":
            raise _KeyFail("HTTP 429: RESOURCE_EXHAUSTED")
        return {"title": "t", "description": "d", "tags": []}

    monkeypatch.setattr(GeminiPool, "_call", staticmethod(fake_call))
    assert pool(book).generate_json("m", "p")["title"] == "t"
    hdr = book.t["GEMINI_KEYS"][0]
    k1, k2 = (dict(zip(hdr, book.t["GEMINI_KEYS"][i])) for i in (1, 2))
    assert k2["So_loi_lien_tiep"] == 1 and k2["Trang_thai"] == "Active" and "429" in k2["Loi_gan_nhat"]
    assert k1["Da_dung_hom_nay"] == 6 and k1["Trang_thai"] == "Active"


def test_gemini_permanent_error_sets_error_immediately(monkeypatch):
    book = make_book([video()])

    def fake_call(model, key, prompt):
        raise _KeyFail("[MODEL] 404 gemini-x: NOT_FOUND", permanent=True)

    monkeypatch.setattr(GeminiPool, "_call", staticmethod(fake_call))
    with pytest.raises(GeminiError):
        pool(book).generate_json("m", "p")
    hdr = book.t["GEMINI_KEYS"][0]
    for i in (1, 2):
        k = dict(zip(hdr, book.t["GEMINI_KEYS"][i]))
        assert k["Trang_thai"] == "Error" and k["Loi_gan_nhat"].startswith("[MODEL]")
        assert gemini.PERMANENT.search(k["Loi_gan_nhat"])        # script reset bên Apps Script sẽ giữ nguyên Error


def test_gemini_three_transient_errors_become_error(monkeypatch):
    book = make_book([video()])
    book.t["GEMINI_KEYS"][1][5] = 2.0       # đã lỗi liên tiếp 2 lần
    monkeypatch.setattr(GeminiPool, "_call", staticmethod(lambda m, k, p: (_ for _ in ()).throw(_KeyFail("HTTP 503"))))
    with pytest.raises(GeminiError):
        pool(book).generate_json("m", "p")
    k1 = dict(zip(book.t["GEMINI_KEYS"][0], book.t["GEMINI_KEYS"][1]))
    assert k1["Trang_thai"] == "Error"


def test_gemini_new_day_resets_counter(monkeypatch):
    book = make_book([video()])
    book.t["GEMINI_KEYS"][1][3] = 500.0      # KEY01 đã chạm giới hạn...
    book.t["GEMINI_KEYS"][1][7] = "2020-01-01 00:00:00"   # ...nhưng là của ngày cũ
    book.t["GEMINI_KEYS"][2][2] = "Error"    # KEY02 đang lỗi
    monkeypatch.setattr(GeminiPool, "_call", staticmethod(lambda m, k, p: {"title": "t", "description": "", "tags": []}))
    pool(book).generate_json("m", "p")
    assert dict(zip(book.t["GEMINI_KEYS"][0], book.t["GEMINI_KEYS"][1]))["Da_dung_hom_nay"] == 1


def test_gemini_no_key_available():
    book = make_book([video()])
    book.t["GEMINI_KEYS"][1][2] = "Error"
    book.t["GEMINI_KEYS"][2][2] = "Error"
    with pytest.raises(GeminiError, match="Active"):
        pool(book).generate_json("m", "p")


def test_parse_json_text_variants():
    p = gemini.parse_json_text
    assert p('```json\n{"title":"a","description":"b","tags":["x","y"]}\n```')["tags"] == ["x", "y"]
    assert p('Đây là kết quả: {"title":"a","tags":"x, y"}')["tags"] == ["x", "y"]
    with pytest.raises(_BadOutput):
        p("không phải json")


def test_build_prompt_replaces_vars_and_adds_json_instruction():
    out = gemini.build_prompt("Video {{Tieu_de_video}} - {{Kenh}} - {{Khong_co}}!", {"Tieu_de_video": "A", "Kenh": "K"})
    assert out.startswith("Video A - K - !") and "JSON" in out
