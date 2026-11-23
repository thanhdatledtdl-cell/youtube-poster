"""Đọc/ghi Google Sheet.

BookBase  : giao diện tối thiểu (read / update / append) để phần còn lại không phụ thuộc gspread.
GSheetBook: bản thật, dùng service account.
Bản giả cho test nằm ở tests/fakes.py.

Quy ước ghi: luôn dùng RAW để chuỗi giữ nguyên là chuỗi (vd Ngay_quota '20261120' phải là TEXT
vì công thức quota trong tab API so sánh với TEXT(...,"yyyymmdd")).
"""
import time
from typing import Dict, List, Tuple

from .util import txt

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


class SheetError(Exception):
    pass


def rows_from_values(vals: List[list]) -> Tuple[List[str], List[dict]]:
    """Bảng giá trị thô -> (tiêu đề, danh sách dòng dạng dict, kèm '_row' = số dòng thật, tính từ 1)."""
    if not vals:
        return [], []
    headers = [txt(h) for h in vals[0]]
    while headers and not headers[-1]:
        headers.pop()
    rows = []
    for i, line in enumerate(vals[1:], start=2):
        d, empty = {"_row": i}, True
        for j, h in enumerate(headers):
            if not h:
                continue
            v = line[j] if j < len(line) else ""
            d[h] = v
            if v not in ("", None):
                empty = False
        if not empty:
            rows.append(d)
    return headers, rows


class BookBase:
    email = ""

    def read(self, name: str) -> Tuple[List[str], List[dict]]:
        raise NotImplementedError

    def update(self, name: str, row: int, values: Dict[str, object]) -> None:
        raise NotImplementedError

    def append(self, name: str, values: Dict[str, object]) -> None:
        raise NotImplementedError


class GSheetBook(BookBase):
    def __init__(self, sheet_id: str, sa_info: dict):
        import gspread
        from google.oauth2.service_account import Credentials
        self._gspread = gspread
        self.creds = Credentials.from_service_account_info(sa_info, scopes=SCOPES)
        self.email = sa_info.get("client_email", "")
        try:
            self.ss = gspread.authorize(self.creds).open_by_key(sheet_id)
        except gspread.exceptions.SpreadsheetNotFound:
            raise SheetError(
                f"Không mở được Sheet. Hãy chia sẻ Sheet (quyền Editor) cho {self.email} "
                "và kiểm tra lại SHEET_ID.")
        except gspread.exceptions.APIError as e:
            raise SheetError(f"Google Sheets API lỗi: {e}. Đã bật 'Google Sheets API' và 'Google Drive API' "
                             "trong dự án Google Cloud của service account chưa?")
        self._ws, self._hdr = {}, {}

    # ---- nội bộ ----
    def _retry(self, fn, tries=5):
        for i in range(tries):
            try:
                return fn()
            except self._gspread.exceptions.APIError as e:
                code = getattr(getattr(e, "response", None), "status_code", 0)
                if code in (429, 500, 502, 503) and i < tries - 1:
                    time.sleep(8 * (i + 1))   # quota Sheets: 60 lần/phút/người dùng
                    continue
                raise

    def _sheet(self, name):
        if name not in self._ws:
            try:
                self._ws[name] = self._retry(lambda: self.ss.worksheet(name))
            except self._gspread.exceptions.WorksheetNotFound:
                raise SheetError(f"Không thấy tab '{name}' trong Sheet (tên tab phải đúng từng ký tự).")
        return self._ws[name]

    def _headers(self, name):
        if name not in self._hdr:
            self.read(name)
        return self._hdr[name]

    # ---- giao diện ----
    def read(self, name):
        ws = self._sheet(name)
        vals = self._retry(lambda: ws.get_all_values(value_render_option="UNFORMATTED_VALUE"))
        headers, rows = rows_from_values(vals)
        self._hdr[name] = headers
        return headers, rows

    def update(self, name, row, values):
        from gspread.utils import rowcol_to_a1
        ws, headers = self._sheet(name), self._headers(name)
        data = []
        for h, v in values.items():
            if h not in headers:
                raise SheetError(f"Tab '{name}' thiếu cột '{h}'")
            data.append({"range": rowcol_to_a1(row, headers.index(h) + 1), "values": [[v]]})
        self._retry(lambda: ws.batch_update(data, value_input_option="RAW"))

    def append(self, name, values):
        ws, headers = self._sheet(name), self._headers(name)
        row = len(self._retry(lambda: ws.col_values(1))) + 1     # dòng trống đầu tiên dưới dữ liệu cột A
        if row > ws.row_count:
            self._retry(lambda: ws.add_rows(row - ws.row_count + 100))
        line = [values.get(h, "") for h in headers]
        self._retry(lambda: ws.batch_update([{"range": f"A{row}", "values": [line]}],
                                            value_input_option="RAW"))
