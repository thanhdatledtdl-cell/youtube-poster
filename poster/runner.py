"""Bộ điều phối - thay vai trò của workflow n8n.

Mỗi lần chạy:
  đọc CONFIG -> với mỗi đường ống (1 kênh x Dài/Ngắn) đến giờ -> chọn video Cho_dang
  -> khóa dòng (Dang_xu_ly) -> Gemini điền ô trống -> tải Drive -> upload YouTube
  -> ghi kết quả vào tab kênh + THEO_DOI.

Ghi Sheet GIỐNG HỆT n8n để 3 script Apps Script (phân bổ, Telegram, reset key) chạy tiếp không đổi.
"""
import os
import re
import tempfile
import traceback
from datetime import timedelta

from . import meta as meta_mod
from . import schedule
from .gemini import GeminiError, GeminiPool, build_prompt
from .util import file_id, fmt_dt, now_vn, num, quota_day, to_dt, truthy, txt

VIDEO_COLS = ["Tieu_de_video", "Link_bai_dang_video", "Tieu_de_youtube", "Mo_ta_youtube", "The_tag",
              "Trang_thai_dang", "Link_Youtube_video", "Thoi_gian_dang_video", "Loi", "So_lan_thu", "Lock_time"]
PRIVACY = ("public", "unlisted", "private")


class Runner:
    def __init__(self, book, creds=None, dry_run=False, force=False, only=None,
                 max_videos=None, privacy=None, workdir=None, now_fn=now_vn):
        self.book, self.creds = book, creds
        self.dry_run, self.force = dry_run, force
        self.only = [x.strip() for x in (only or []) if x.strip()]
        self.max_videos, self.privacy = max_videos, privacy
        self.workdir = workdir or tempfile.mkdtemp(prefix="yt_")
        self.now_fn = now_fn
        self.results = []          # để in bảng tổng kết
        self.sysc = {}

    # ------------------------------------------------------------------ điểm móc (test thay thế được)
    def make_yt(self, api):
        from . import youtube
        return youtube.build_client(txt(api["Client_ID"]), txt(api["Client_Secret"]), txt(api["Refresh_Token"]))

    def download(self, fid, dest):
        from . import drive
        return drive.download(self.creds, fid, dest)

    def upload(self, yt, path, m, category, privacy):
        from . import youtube
        return youtube.upload(yt, path, m["title"], m["description"], m["tags"], category, privacy)

    def gen_json(self, model, prompt):
        pool = GeminiPool(self.book, self.sysc["gemini_so_key"], self.sysc["gemini_max_loi_key"])
        return pool.generate_json(model, prompt)

    # ------------------------------------------------------------------ vòng chạy chính
    def load_system(self):
        _, rows = self.book.read("HE_THONG")
        d = {txt(r.get("Khoa")): r.get("Gia_tri") for r in rows if txt(r.get("Khoa"))}
        self.sysc = {
            "tol": num(d.get("TOLERANCE_PHUT"), 5),
            "max_loi": int(num(d.get("MAX_LOI"), 3)),
            "lock": num(d.get("LOCK_PHUT"), 30),
            "quota_video": num(d.get("QUOTA_MOI_VIDEO"), 1600) or 1600,
            "gemini_so_key": int(num(d.get("GEMINI_SO_KEY_THU"), 3)),
            "gemini_max_loi_key": int(num(d.get("GEMINI_MAX_LOI_KEY"), 3)),
        }
        return self.sysc

    def run(self):
        sysc = self.load_system()
        _, config = self.book.read("CONFIG")
        _, apis = self.book.read("API")
        _, prompts = self.book.read("PROMPT")
        api_by = {txt(a.get("API_name")): a for a in apis if txt(a.get("Loai")).lower() == "youtube"}
        prompt_by = {txt(p.get("Prompt_name")): p for p in prompts if truthy(p.get("Active"))}
        now = self.now_fn()
        print(f"Giờ VN: {fmt_dt(now)} | dung sai ±{sysc['tol']:g} phút | "
              f"{'XEM THỬ (không ghi, không đăng)' if self.dry_run else 'ĐĂNG THẬT'}"
              f"{' | bỏ qua lọc giờ' if self.force else ''}")
        if sysc["tol"] < 15 and not self.force:
            print("::warning::TOLERANCE_PHUT quá nhỏ cho GitHub Actions (cron hay trễ 5-30 phút). "
                  "Nên đặt 25 trong tab HE_THONG.")
        known = {txt(p.get("ID")) for p in config}
        for x in self.only:
            if x not in known:
                print(f"::error::Không có đường ống '{x}' trong CONFIG (ID có: {', '.join(sorted(known))})")
        for p in config:
            pid = txt(p.get("ID"))
            if not pid or (self.only and pid not in self.only):
                continue
            try:
                self._pipeline(p, api_by, prompt_by, now)
            except Exception as e:  # noqa: BLE001 - 1 đường ống lỗi không được kéo sập các đường ống khác
                traceback.print_exc()
                self._note(pid, "LỖI", f"{type(e).__name__}: {e}")
                print(f"::error::{pid}: {type(e).__name__}: {e}")
        self._summary()
        return self.results

    # ------------------------------------------------------------------ 1 đường ống
    def _note(self, pid, status, msg, posted=0, failed=0):
        self.results.append({"id": pid, "status": status, "msg": msg, "posted": posted, "failed": failed})
        print(f"[{pid}] {status}: {msg}")

    def _pipeline(self, p, api_by, prompt_by, now):
        sysc, pid = self.sysc, txt(p.get("ID"))
        tab = txt(p.get("Tab_du_lieu"))
        if not truthy(p.get("Active")) and not self.only:
            return self._note(pid, "BỎ QUA", "Active = FALSE")
        if not tab:
            return self._note(pid, "LỖI", "CONFIG thiếu Tab_du_lieu")

        headers, rows = self.book.read(tab)
        miss = [c for c in VIDEO_COLS if c not in headers]
        if miss:
            return self._note(pid, "LỖI", f"Tab {tab} thiếu cột: {', '.join(miss)}")

        # --- lọc giờ
        if not self.force:
            slots = schedule.parse_slots(txt(p.get("Gio_dang")))
            slot = schedule.due_slot(now, slots, sysc["tol"])
            if slot is None:
                return self._note(pid, "CHƯA ĐẾN GIỜ", f"Gio_dang = '{txt(p.get('Gio_dang')) or '(mỗi giờ)'}'")
            posted_times = [to_dt(r.get("Thoi_gian_dang_video")) for r in rows
                            if txt(r.get("Trang_thai_dang")) == "Done"]
            if schedule.already_served([t for t in posted_times if t], slot, sysc["tol"]):
                return self._note(pid, "BỎ QUA", f"đã đăng cho khung giờ {slot:%H:%M}")

        # --- API / quota
        api = api_by.get(txt(p.get("API_name")))
        if not api:
            return self._note(pid, "LỖI", f"Không thấy API_name '{txt(p.get('API_name'))}' (loại youtube) trong tab API")
        if txt(api.get("Trang_thai")) not in ("OK", ""):
            return self._note(pid, "BỎ QUA", f"API {txt(api.get('API_name'))} Trang_thai = {txt(api.get('Trang_thai'))}")
        for c in ("Client_ID", "Client_Secret", "Refresh_Token"):
            if not txt(api.get(c)):
                return self._note(pid, "LỖI", f"Tab API dòng {txt(api.get('API_name'))} thiếu {c}")

        n = int(num(p.get("So_video"), 1)) or 1
        if self.max_videos:
            n = min(n, self.max_videos)
        left = txt(api.get("Quota_con_lai"))
        if left != "":
            n = min(n, int(num(left) // sysc["quota_video"]))
        if n <= 0:
            return self._note(pid, "HẾT QUOTA", f"Quota_con_lai = {left}, mỗi video cần {sysc['quota_video']:g}")

        # --- chọn video
        pending = self._pending(rows, now)[:n]
        if not pending:
            return self._note(pid, "KHÔNG CÓ VIDEO", "không có dòng nào Cho_dang")

        privacy = self.privacy or txt(p.get("Privacy")).lower() or "private"
        if privacy not in PRIVACY:
            return self._note(pid, "LỖI", f"Privacy '{privacy}' không hợp lệ (public/unlisted/private)")

        if self.dry_run:
            for r, stale in pending:
                print(f"   - sẽ đăng: {txt(r.get('Tieu_de_video'))[:70]} | {txt(r.get('Link_bai_dang_video'))[:60]}")
            return self._note(pid, "XEM THỬ", f"sẽ đăng {len(pending)} video, privacy={privacy}, API={txt(api.get('API_name'))}")

        from .youtube import AuthError
        try:
            yt = self.make_yt(api)
        except AuthError as e:
            print(f"::error::{pid}: {e}")
            return self._note(pid, "LỖI TOKEN", str(e))

        prompt = prompt_by.get(txt(p.get("Prompt_name")))
        posted = failed = 0
        for r, stale in pending:
            code = self._video(p, api, yt, prompt, tab, r, stale, privacy)
            if code == "ok":
                posted += 1
            elif code == "fail":
                failed += 1
            elif code == "quota":
                self._note(pid, "HẾT QUOTA", "YouTube từ chối vì hết quota/giới hạn upload, dừng đường ống này",
                           posted, failed)
                return
        self._note(pid, "XONG", f"đăng {posted}, lỗi {failed}", posted, failed)

    def _pending(self, rows, now):
        """Video đến lượt: Cho_dang, hoặc Dang_xu_ly bị kẹt quá LOCK_PHUT. Thứ tự từ trên xuống."""
        out = []
        for r in rows:
            if not txt(r.get("Link_bai_dang_video")):
                continue
            st = txt(r.get("Trang_thai_dang"))
            if st == "Cho_dang":
                out.append((r, False))
            elif st == "Dang_xu_ly":
                lt = to_dt(r.get("Lock_time"))
                if lt is None or now - lt > timedelta(minutes=self.sysc["lock"]):
                    out.append((r, True))
        return out

    # ------------------------------------------------------------------ 1 video
    def _locate(self, tab, link, statuses):
        _, rows = self.book.read(tab)
        for r in rows:
            if txt(r.get("Link_bai_dang_video")) == link and txt(r.get("Trang_thai_dang")) in statuses:
                return r
        return None

    def _video(self, p, api, yt, prompt, tab, row, stale, privacy):
        sysc, pid = self.sysc, txt(p.get("ID"))
        link = txt(row.get("Link_bai_dang_video"))
        src_title = txt(row.get("Tieu_de_video"))
        expect = ("Dang_xu_ly",) if stale else ("Cho_dang",)

        # 1) khóa dòng
        cur = self._locate(tab, link, expect)
        if cur is None:
            print(f"   dòng đã bị đổi trạng thái, bỏ qua: {src_title[:50]}")
            return "skip"
        lock = {"Trang_thai_dang": "Dang_xu_ly", "Lock_time": fmt_dt(self.now_fn())}
        if stale:
            thu = int(num(cur.get("So_lan_thu"))) + 1
            lock["So_lan_thu"] = thu
            if thu >= sysc["max_loi"]:
                self.book.update(tab, cur["_row"], {**lock, "Trang_thai_dang": "Loi", "Lock_time": "",
                                                    "Loi": "[kẹt] Dang_xu_ly quá lâu nhiều lần (job bị hủy/treo?)"})
                self._log(p, api, src_title, False, "", "kẹt Dang_xu_ly quá số lần", 0)
                return "fail"
        self.book.update(tab, cur["_row"], lock)

        stage, final, path = "chuẩn bị", None, None
        try:
            fid = file_id(link)
            if not fid:
                raise ValueError(f"Không tách được ID file Drive từ link: {link[:80]}")
            stage = "gemini"
            m = self._meta(p, row, prompt)
            final = m
            stage = "tải Drive"
            path = os.path.join(self.workdir, f"{fid}.mp4")
            size = self.download(fid, path)
            print(f"   đã tải {size / 1_048_576:.1f} MB: {src_title[:50]}")
            stage = "upload"
            category = int(num(p.get("Category_id"), 22)) or 22
            vid = self.upload(yt, path, m, category, privacy)
        except Exception as e:  # noqa: BLE001
            from .youtube import QuotaError
            if isinstance(e, QuotaError):
                self._release(tab, link)
                return "quota"
            return self._fail(p, api, tab, link, src_title, final, stage, e)
        finally:
            if path and os.path.exists(path):
                os.remove(path)

        # 2) ghi kết quả
        url = f"https://www.youtube.com/watch?v={vid}"
        done = {"Tieu_de_youtube": m["title"], "Mo_ta_youtube": m["description"],
                "The_tag": ", ".join(m["tags"]), "Trang_thai_dang": "Done", "Link_Youtube_video": url,
                "Thoi_gian_dang_video": fmt_dt(self.now_fn()), "Loi": "", "Lock_time": ""}
        cur = self._locate(tab, link, ("Dang_xu_ly",))
        if cur is not None:
            self.book.update(tab, cur["_row"], done)
        else:
            print(f"::warning::{pid}: video đã lên YouTube ({url}) nhưng không tìm lại được dòng để ghi Done")
        self._log(p, api, m["title"], True, url, "", sysc["quota_video"])
        print(f"   ✅ {url} ({privacy})")
        return "ok"

    def _meta(self, p, row, prompt):
        title, desc = txt(row.get("Tieu_de_youtube")), str(row.get("Mo_ta_youtube") or "").strip()
        tags = [t.strip() for t in re.split(r"[,\n]", txt(row.get("The_tag"))) if t.strip()]
        if not (title and desc and tags):          # chỉ gọi AI khi thiếu ô; ô đã có giữ nguyên
            if prompt is None:
                raise GeminiError(f"Thiếu prompt: Prompt_name '{txt(p.get('Prompt_name'))}' không có trong tab PROMPT "
                                  "hoặc Active = FALSE")
            variables = {k: v for k, v in row.items() if not k.startswith("_")}
            variables.update({"Kenh": txt(p.get("Kenh")), "Loai": txt(p.get("Loai")), "ID": txt(p.get("ID"))})
            data = self.gen_json(txt(prompt.get("Model")) or "gemini-2.5-flash",
                                 build_prompt(txt(prompt.get("Noi_dung")), variables))
            title, desc, tags = title or data["title"], desc or data["description"], tags or data["tags"]
        if not title:
            raise GeminiError("Không có tiêu đề (Gemini không trả title)")
        return meta_mod.finalize(title, desc, tags, is_short=txt(p.get("Loai")).lower() == "ngan")

    # ------------------------------------------------------------------ ghi nhận lỗi / nhật ký
    def _release(self, tab, link):
        cur = self._locate(tab, link, ("Dang_xu_ly",))
        if cur is not None:
            self.book.update(tab, cur["_row"], {"Trang_thai_dang": "Cho_dang", "Lock_time": ""})

    def _fail(self, p, api, tab, link, src_title, final, stage, e):
        msg = f"[{stage}] {type(e).__name__}: {e}"[:500]
        cur = self._locate(tab, link, ("Dang_xu_ly",))
        if cur is not None:
            thu = int(num(cur.get("So_lan_thu"))) + 1
            status = "Loi" if thu >= self.sysc["max_loi"] else "Cho_dang"
            self.book.update(tab, cur["_row"], {"Trang_thai_dang": status, "So_lan_thu": thu,
                                                "Loi": msg, "Lock_time": ""})
        cost = self.sysc["quota_video"] if stage == "upload" else 0    # lỗi trước khi gọi YouTube thì không tốn quota
        self._log(p, api, (final or {}).get("title") or src_title, False, "", msg, cost)
        print(f"   ❌ {msg}")
        print(f"::error::{txt(p.get('ID'))}: {msg}")
        return "fail"

    def _log(self, p, api, title, ok, link, err, cost):
        self.book.append("THEO_DOI", {
            "Thoi_gian": fmt_dt(self.now_fn()), "ID": txt(p.get("ID")), "Kenh": txt(p.get("Kenh")),
            "Loai": txt(p.get("Loai")), "Tieu_de": title[:100], "Ket_qua": "Done" if ok else "Loi",
            "Link": link, "Loi": err[:500], "API_name": txt(api.get("API_name")),
            "Ngay_quota": quota_day(), "Quota_cost": cost,
            "Du_an": txt(api.get("Du_an")) or txt(api.get("API_name"))})

    # ------------------------------------------------------------------ tổng kết
    def _summary(self):
        lines = ["| Đường ống | Kết quả | Chi tiết |", "|---|---|---|"]
        lines += [f"| {r['id']} | {r['status']} | {r['msg']} |" for r in self.results]
        text = "\n".join(lines)
        print("\n" + text)
        path = os.environ.get("GITHUB_STEP_SUMMARY")
        if path:
            with open(path, "a", encoding="utf-8") as f:
                f.write("### Kết quả chạy\n\n" + text + "\n")
