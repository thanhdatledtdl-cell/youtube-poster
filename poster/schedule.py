"""Đọc cột Gio_dang và quyết định 'đến giờ đăng chưa'.

Cú pháp Gio_dang (giờ Việt Nam), giống tài liệu HUONG_DAN:
  "07:00,11:00,15:00"     liệt kê
  "06:00-21:00/3"         từ 06:00 đến 21:00, cứ 3 giờ một lần (06,09,12,15,18,21)
  trộn hai kiểu, cách nhau dấu phẩy
  để trống                mỗi giờ đều đăng
"""
import re
from datetime import datetime, timedelta
from typing import List, Optional

_T = r"(\d{1,2}):(\d{2})(?::\d{2})?"
_RANGE = re.compile(rf"\s*{_T}\s*-\s*{_T}\s*/\s*(\d+)\s*$")
_ONE = re.compile(rf"\s*{_T}\s*$")


def _minutes(h: str, m: str) -> int:
    h, m = int(h), int(m)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"Giờ không hợp lệ: {h}:{m:02d}")
    return h * 60 + m


def parse_slots(text: str) -> Optional[List[int]]:
    """Trả về danh sách phút-trong-ngày đã sắp xếp. None nghĩa là 'để trống = mỗi giờ'."""
    text = (text or "").strip()
    if not text:
        return None
    slots = set()
    for part in re.split(r"[,;]", text):
        if not part.strip():
            continue
        m = _RANGE.match(part)
        if m:
            a = _minutes(m.group(1), m.group(2))
            b = _minutes(m.group(3), m.group(4))
            step = int(m.group(5))
            if step <= 0:
                raise ValueError(f"Bước nhảy phải > 0: '{part.strip()}'")
            t = a
            while t <= b:
                slots.add(t)
                t += step * 60
            continue
        m = _ONE.match(part)
        if not m:
            raise ValueError(f"Không hiểu Gio_dang: '{part.strip()}'")
        slots.add(_minutes(m.group(1), m.group(2)))
    return sorted(slots)


def due_slot(now: datetime, slots: Optional[List[int]], tol_min: float) -> Optional[datetime]:
    """Khung giờ gần 'now' nhất trong phạm vi ±tol_min phút; None nếu chưa đến giờ."""
    if slots is None:
        slots = [h * 60 for h in range(24)]
    base = now.replace(hour=0, minute=0, second=0, microsecond=0)
    best = None
    for off in (-1, 0, 1):   # xét cả hôm qua/ngày mai để xử lý sát nửa đêm
        for s in slots:
            dt = base + timedelta(days=off, minutes=s)
            d = abs((now - dt).total_seconds()) / 60
            if d <= tol_min and (best is None or d < best[0]):
                best = (d, dt)
    return best[1] if best else None


def already_served(posted: List[datetime], slot: datetime, tol_min: float) -> bool:
    """Đã có video đăng trong khung giờ này chưa (chống đăng trùng khi bấm chạy 2 lần)."""
    return any(abs((p - slot).total_seconds()) / 60 <= tol_min for p in posted)
