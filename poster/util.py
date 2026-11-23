"""Hàm tiện ích: thời gian, ép kiểu giá trị ô Google Sheet, tách file ID Drive."""
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

VN = ZoneInfo("Asia/Ho_Chi_Minh")
PT = ZoneInfo("America/Los_Angeles")   # YouTube reset quota lúc 0h giờ Thái Bình Dương
_EPOCH = datetime(1899, 12, 30)        # gốc ngày tháng của Google Sheets


def now_vn() -> datetime:
    return datetime.now(VN)


def fmt_dt(dt: datetime) -> str:
    """'2026-10-08 14:46:38' theo giờ VN - đúng định dạng n8n đang ghi."""
    return dt.astimezone(VN).strftime("%Y-%m-%d %H:%M:%S")


def quota_day(dt: datetime = None) -> str:
    """Ngày quota 'yyyymmdd' theo giờ Thái Bình Dương (cột Ngay_quota trong THEO_DOI, dạng TEXT)."""
    return (dt or datetime.now(PT)).astimezone(PT).strftime("%Y%m%d")


def to_dt(v):
    """Ô Sheet -> datetime giờ VN. Nhận chuỗi, hoặc số serial của Google Sheets. Không đọc được -> None."""
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return (_EPOCH + timedelta(days=float(v))).replace(tzinfo=VN)
    s = str(v).strip()
    for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S",
              "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(s, f).replace(tzinfo=VN)
        except ValueError:
            pass
    return None


def num(v, default=0.0) -> float:
    if v is None or v == "":
        return default
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip().replace(",", "."))
    except ValueError:
        return default


def txt(v) -> str:
    """Ô Sheet -> chuỗi sạch. 3.0 -> '3', None -> ''."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def truthy(v) -> bool:
    return v is True or str(v).strip().upper() in {"TRUE", "1", "YES", "CÓ", "CO"}


_FID = (re.compile(r"/d/([A-Za-z0-9_-]+)"), re.compile(r"[?&]id=([A-Za-z0-9_-]+)"))


def file_id(url) -> str:
    """Lấy ID file từ link Google Drive (/file/d/ID/view hoặc ...?id=ID)."""
    s = str(url or "")
    for rx in _FID:
        m = rx.search(s)
        if m:
            return m.group(1)
    return ""
