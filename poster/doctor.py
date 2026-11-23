"""python -m poster doctor : kiểm tra mọi thứ TRƯỚC khi đăng thật (không ghi gì vào Sheet, không đăng)."""
from . import schedule
from .sheet import SheetError
from .util import file_id, num, truthy, txt

NEED = {
    "CONFIG": ["ID", "Kenh", "Loai", "Tab_du_lieu", "Active", "Gio_dang", "So_video", "Privacy",
               "Category_id", "API_name", "Prompt_name"],
    "API": ["API_name", "Loai", "Client_ID", "Client_Secret", "Refresh_Token", "Du_an", "Quota_con_lai", "Trang_thai"],
    "GEMINI_KEYS": ["Key_ID", "API_Key", "Trang_thai", "Da_dung_hom_nay", "Gioi_han_ngay",
                    "So_loi_lien_tiep", "Loi_gan_nhat", "Cap_nhat_luc"],
    "PROMPT": ["Prompt_name", "Noi_dung", "Model", "Active"],
    "HE_THONG": ["Khoa", "Gia_tri"],
    "THEO_DOI": ["Thoi_gian", "ID", "Kenh", "Loai", "Tieu_de", "Ket_qua", "Link", "Loi",
                 "API_name", "Ngay_quota", "Quota_cost", "Du_an"],
}
VIDEO_COLS = ["Tieu_de_video", "Link_bai_dang_video", "Tieu_de_youtube", "Mo_ta_youtube", "The_tag",
              "Trang_thai_dang", "Link_Youtube_video", "Thoi_gian_dang_video", "Loi", "So_lan_thu", "Lock_time"]


def run_doctor(book, creds, only) -> bool:
    ok_all = True

    def say(ok, good, bad=""):
        nonlocal ok_all
        ok_all &= bool(ok)
        print(("✅ " if ok else "❌ ") + (good if ok else (bad or good)))
        return ok

    def warn(msg):
        print("⚠️  " + msg)

    print(f"Service account: {book.email or '(không rõ)'}")
    tables = {}
    for tab, cols in NEED.items():
        try:
            headers, rows = book.read(tab)
        except SheetError as e:
            say(False, "", str(e))
            continue
        miss = [c for c in cols if c not in headers]
        say(not miss, f"Tab {tab}: đủ cột ({len(rows)} dòng)", f"Tab {tab} thiếu cột: {', '.join(miss)}")
        tables[tab] = rows
    if not all(t in tables for t in ("CONFIG", "API", "HE_THONG", "PROMPT", "GEMINI_KEYS")):
        return False

    sysd = {txt(r.get("Khoa")): r.get("Gia_tri") for r in tables["HE_THONG"]}
    tol = num(sysd.get("TOLERANCE_PHUT"), 5)
    if tol < 15:
        warn(f"TOLERANCE_PHUT = {tol:g}: quá nhỏ cho GitHub Actions (cron hay trễ 5-30 phút). Nên đặt 25. "
             "(Khi chạy tay với --force thì không ảnh hưởng.)")
    else:
        say(True, f"TOLERANCE_PHUT = {tol:g}")

    keys = [r for r in tables["GEMINI_KEYS"] if txt(r.get("API_Key"))]
    act = [r for r in keys if txt(r.get("Trang_thai")) == "Active"]
    say(bool(act), f"Gemini: {len(act)}/{len(keys)} key Active", "Gemini: KHÔNG có key Active nào")

    api_by = {txt(a.get("API_name")): a for a in tables["API"] if txt(a.get("Loai")).lower() == "youtube"}
    prompts = {txt(p.get("Prompt_name")): p for p in tables["PROMPT"] if truthy(p.get("Active"))}

    from . import drive, youtube
    for p in tables["CONFIG"]:
        pid = txt(p.get("ID"))
        if not pid or (only and pid not in only) or (not only and not truthy(p.get("Active"))):
            continue
        print(f"\n— Đường ống {pid} —")
        try:
            slots = schedule.parse_slots(txt(p.get("Gio_dang")))
            say(True, "Gio_dang = " + (", ".join(f"{s // 60:02d}:{s % 60:02d}" for s in slots) if slots else "(mỗi giờ)"))
        except ValueError as e:
            say(False, "", f"Gio_dang sai cú pháp: {e}")
        tab = txt(p.get("Tab_du_lieu"))
        try:
            headers, rows = book.read(tab)
            miss = [c for c in VIDEO_COLS if c not in headers]
            say(not miss, f"Tab {tab}: đủ cột", f"Tab {tab} thiếu cột: {', '.join(miss)}")
            cho = [r for r in rows if txt(r.get("Trang_thai_dang")) == "Cho_dang" and txt(r.get("Link_bai_dang_video"))]
            say(bool(cho), f"{len(cho)} video Cho_dang", "Không có video nào Cho_dang")
        except SheetError as e:
            say(False, "", str(e))
            cho = []
        api = api_by.get(txt(p.get("API_name")))
        if not say(api is not None, f"API_name {txt(p.get('API_name'))}", f"Không thấy API_name '{txt(p.get('API_name'))}'"):
            continue
        have = all(txt(api.get(c)) for c in ("Client_ID", "Client_Secret", "Refresh_Token"))
        if say(have, "Có đủ Client_ID/Secret/Refresh_Token", "Thiếu Client_ID, Client_Secret hoặc Refresh_Token"):
            err = youtube.refresh_check(txt(api["Client_ID"]), txt(api["Client_Secret"]), txt(api["Refresh_Token"]))
            say(err is None, "Refresh token đổi được access token", err or "")
        left = txt(api.get("Quota_con_lai"))
        if left != "":
            say(num(left) >= 1600, f"Quota còn {num(left):g} (~{int(num(left) // 1600)} video)",
                f"Quota còn {num(left):g}: không đủ 1 video")
        if txt(p.get("Prompt_name")) not in prompts:
            warn(f"Prompt '{txt(p.get('Prompt_name'))}' không có/không Active: video thiếu tiêu đề-mô tả-tag sẽ lỗi")
        if cho and creds is not None:
            fid = file_id(cho[0].get("Link_bai_dang_video"))
            if not fid:
                say(False, "", "Link video đầu tiên không tách được ID Drive")
            else:
                good, msg = drive.probe(creds, fid)
                (say(True, f"Drive đọc được: {msg}") if good else warn(f"Drive: {msg}"))
    print("\n" + ("KẾT LUẬN: sẵn sàng." if ok_all else "KẾT LUẬN: còn mục ❌ cần sửa trước khi đăng thật."))
    return ok_all
