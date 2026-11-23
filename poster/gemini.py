"""Gọi Gemini để sinh tiêu đề / mô tả / tag, xoay vòng key trong tab GEMINI_KEYS.

Quy tắc giống n8n (xem HUONG_DAN mục 5):
- Chỉ dùng key Trang_thai = Active còn lượt (Da_dung_hom_nay < Gioi_han_ngay), chọn key dùng ít nhất.
- Gọi lỗi thì thử key kế tiếp, tối đa GEMINI_SO_KEY_THU key mỗi lần.
- Một key lỗi liên tiếp GEMINI_MAX_LOI_KEY lần thì chuyển Error. Lỗi vĩnh viễn (sai key, sai model)
  chuyển Error ngay; script reset bên Apps Script nhận ra các lỗi này và KHÔNG tự bật lại.
- Da_dung_hom_nay tự về 0 khi Cap_nhat_luc không phải hôm nay (giờ VN).
"""
import json
import re
from typing import Dict

import requests

from .util import fmt_dt, now_vn, num, to_dt, txt

# Giữ khớp với PERMANENT_ERROR trong file Apps Script reset key.
PERMANENT = re.compile(
    r"API_KEY_INVALID|API key not valid|PERMISSION_DENIED|suspended|disabled|has been denied|"
    r"no longer available|NOT_FOUND|\[MODEL\]", re.I)

JSON_SUFFIX = (
    "\n\nCHỈ trả về một đối tượng JSON hợp lệ, không markdown, không giải thích, đúng dạng: "
    '{"title": "...", "description": "...", "tags": ["...", "..."]}'
)


class GeminiError(Exception):
    pass


class _KeyFail(Exception):
    def __init__(self, msg, permanent=False):
        super().__init__(msg)
        self.msg, self.permanent = msg, permanent


class _BadOutput(Exception):
    pass


def build_prompt(template: str, variables: Dict[str, object]) -> str:
    """Thay {{Ten_cot}} bằng giá trị trong dòng video / CONFIG. Biến không có -> chuỗi rỗng."""
    def rep(m):
        return txt(variables.get(m.group(1).strip(), ""))
    return re.sub(r"\{\{\s*([^}]+?)\s*\}\}", rep, template) + JSON_SUFFIX


def parse_json_text(text: str) -> dict:
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.I).strip()
    try:
        data = json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, re.S)
        if not m:
            raise _BadOutput("Gemini không trả JSON")
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            raise _BadOutput("JSON của Gemini bị hỏng")
    if isinstance(data, list) and data:
        data = data[0]
    if not isinstance(data, dict):
        raise _BadOutput("JSON của Gemini không phải đối tượng")
    tags = data.get("tags", [])
    if isinstance(tags, str):
        tags = [x.strip() for x in re.split(r"[,\n]", tags) if x.strip()]
    return {"title": txt(data.get("title")), "description": str(data.get("description") or "").strip(),
            "tags": [txt(x) for x in tags if txt(x)]}


class GeminiPool:
    def __init__(self, book, so_key_thu=3, max_loi_key=3):
        self.book, self.so_key_thu, self.max_loi_key = book, int(so_key_thu), int(max_loi_key)

    def generate_json(self, model: str, prompt: str) -> dict:
        _, rows = self.book.read("GEMINI_KEYS")
        today = now_vn().date()
        cands = []
        for r in rows:
            key = txt(r.get("API_Key"))
            if not key or txt(r.get("Trang_thai")) != "Active":
                continue
            used = num(r.get("Da_dung_hom_nay"))
            cap = to_dt(r.get("Cap_nhat_luc"))
            if cap is None or cap.date() != today:
                used = 0                       # sang ngày mới -> đếm lại từ 0
            limit = num(r.get("Gioi_han_ngay"), 500) or 500
            if used < limit:
                cands.append((used, r, key))
        if not cands:
            raise GeminiError("Không còn key Gemini nào Active và còn lượt trong ngày (xem tab GEMINI_KEYS)")
        cands.sort(key=lambda c: c[0])

        last = ""
        for used, r, key in cands[: self.so_key_thu]:
            stamp = fmt_dt(now_vn())
            try:
                data = self._call(model, key, prompt)
            except _KeyFail as e:
                n = int(num(r.get("So_loi_lien_tiep"))) + 1
                status = "Error" if (e.permanent or n >= self.max_loi_key) else "Active"
                self.book.update("GEMINI_KEYS", r["_row"], {
                    "Da_dung_hom_nay": int(used), "So_loi_lien_tiep": n, "Loi_gan_nhat": e.msg[:300],
                    "Trang_thai": status, "Cap_nhat_luc": stamp})
                last = f"{txt(r.get('Key_ID'))}: {e.msg}"
                continue
            except _BadOutput as e:
                # key vẫn hoạt động (đã tốn 1 lượt) nhưng đầu ra không dùng được -> thử key khác
                self.book.update("GEMINI_KEYS", r["_row"], {
                    "Da_dung_hom_nay": int(used) + 1, "So_loi_lien_tiep": 0, "Cap_nhat_luc": stamp})
                last = f"{txt(r.get('Key_ID'))}: {e}"
                continue
            self.book.update("GEMINI_KEYS", r["_row"], {
                "Da_dung_hom_nay": int(used) + 1, "So_loi_lien_tiep": 0, "Loi_gan_nhat": "",
                "Cap_nhat_luc": stamp})
            return data
        raise GeminiError(f"Gemini lỗi sau {min(len(cands), self.so_key_thu)} key. Lỗi cuối: {last}")

    @staticmethod
    def _call(model: str, key: str, prompt: str) -> dict:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        try:
            resp = requests.post(
                url, headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                json={"contents": [{"parts": [{"text": prompt}]}],
                      "generationConfig": {"responseMimeType": "application/json",
                                           "temperature": 0.7, "maxOutputTokens": 4096}},
                timeout=120)
        except requests.RequestException as e:
            raise _KeyFail(f"network: {e}")
        if resp.status_code != 200:
            body = resp.text[:300].replace("\n", " ")
            msg = f"[MODEL] 404 {model}: {body}" if resp.status_code == 404 else f"HTTP {resp.status_code}: {body}"
            raise _KeyFail(msg, permanent=bool(PERMANENT.search(msg)))
        try:
            parts = resp.json()["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts)
        except (KeyError, IndexError, TypeError, ValueError):
            raise _BadOutput("Gemini trả về rỗng (có thể bị chặn bộ lọc an toàn)")
        return parse_json_text(text)
