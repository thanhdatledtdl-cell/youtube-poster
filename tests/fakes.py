"""Sheet giả trong bộ nhớ: cùng giao diện với GSheetBook nhưng không gọi mạng."""
from poster.sheet import BookBase, SheetError, rows_from_values
from poster.util import fmt_dt, now_vn, txt


class FakeBook(BookBase):
    email = "fake@test.iam"

    def __init__(self, tables):
        self.t = {k: [list(r) for r in v] for k, v in tables.items()}

    def read(self, name):
        if name not in self.t:
            raise SheetError(f"Không thấy tab '{name}'")
        return rows_from_values(self.t[name])

    def _hdr(self, name):
        h = [txt(x) for x in self.t[name][0]]
        while h and not h[-1]:
            h.pop()
        return h

    def update(self, name, row, values):
        h = self._hdr(name)
        while len(self.t[name]) < row:
            self.t[name].append([])
        line = self.t[name][row - 1]
        for k, v in values.items():
            i = h.index(k)
            while len(line) <= i:
                line.append("")
            line[i] = v

    def append(self, name, values):
        h = self._hdr(name)
        self.t[name].append([values.get(k, "") for k in h])

    # tiện cho test
    def row(self, name, row):
        h, rows = self.read(name)
        return next(r for r in rows if r["_row"] == row)


def make_book(video_rows, quota_left=10000, extra_api=None):
    """Bộ dữ liệu tối thiểu: 1 đường ống T_NGAN (kênh T, ngắn) + 1 key Gemini + 1 prompt."""
    vh = ["Tieu_de_video", "Link_bai_dang_video", "Tieu_de_youtube", "Mo_ta_youtube", "The_tag",
          "Trang_thai_dang", "Link_Youtube_video", "Thoi_gian_dang_video", "Loi", "So_lan_thu", "Lock_time"]
    api = [["API_name", "Loai", "Client_ID", "Client_Secret", "Refresh_Token", "Du_an", "Quota_toi_da",
            "Quota_da_dung", "Trang_thai", "Quota_con_lai"],
           ["YT_T", "youtube", "cid", "sec", "rt", "PROJECT_1", 10000, 0, "OK", quota_left]]
    cfg = [["ID", "Kenh", "Loai", "Tab_du_lieu", "Active", "Gio_dang", "So_video", "Privacy",
            "Category_id", "API_name", "Prompt_name"],
           ["T_NGAN", "Kenh_T", "Ngan", "Kenh_T_Ngan", True, "10:00,16:00", 1.0, "public", 26.0, "YT_T", "Prompt_Ngan"]]
    return FakeBook({
        "HE_THONG": [["Khoa", "Gia_tri"], ["TOLERANCE_PHUT", 25.0], ["MAX_LOI", 3.0], ["LOCK_PHUT", 30.0],
                     ["QUOTA_MOI_VIDEO", 1600.0], ["GEMINI_MAX_LOI_KEY", 3.0], ["GEMINI_SO_KEY_THU", 3.0]],
        "CONFIG": cfg,
        "API": api + (extra_api or []),
        "PROMPT": [["Prompt_name", "Noi_dung", "Model", "Active"],
                   ["Prompt_Ngan", "Viết tiêu đề cho: {{Tieu_de_video}} ({{Kenh}})", "gemini-2.5-flash", True]],
        "GEMINI_KEYS": [["Key_ID", "API_Key", "Trang_thai", "Da_dung_hom_nay", "Gioi_han_ngay",
                         "So_loi_lien_tiep", "Loi_gan_nhat", "Cap_nhat_luc"],
                        ["KEY01", "AIzaA", "Active", 5.0, 500.0, 0.0, "", fmt_dt(now_vn())],
                        ["KEY02", "AIzaB", "Active", 1.0, 500.0, 0.0, "", fmt_dt(now_vn())]],
        "THEO_DOI": [["Thoi_gian", "ID", "Kenh", "Loai", "Tieu_de", "Ket_qua", "Link", "Loi",
                      "API_name", "Ngay_quota", "Quota_cost", "Du_an"],
                     ["n8n tự ghi từ dòng này. Dòng này có thể xóa."]],
        "Kenh_T_Ngan": [vh] + video_rows,
    })


def video(title="Video 1", fid="AAA111", status="Cho_dang", **kw):
    base = {"Tieu_de_video": title, "Link_bai_dang_video": f"https://drive.google.com/file/d/{fid}/view",
            "Tieu_de_youtube": "", "Mo_ta_youtube": "", "The_tag": "", "Trang_thai_dang": status,
            "Link_Youtube_video": "", "Thoi_gian_dang_video": "", "Loi": "", "So_lan_thu": "", "Lock_time": ""}
    base.update(kw)
    return list(base.values())
