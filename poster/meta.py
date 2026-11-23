"""Chuẩn hóa metadata video theo giới hạn của YouTube.

- Tiêu đề tối đa 100 ký tự, mô tả tối đa 5000 BYTE (tiếng Việt tốn 2-3 byte/ký tự), không chứa < >.
- Tổng độ dài tag tối đa 500 ký tự.
- Loai = Ngan: tự thêm #Shorts vào tiêu đề và mô tả (nếu chưa có).
"""
from typing import List

SHORTS = "#Shorts"


def _strip(s: str) -> str:
    return (s or "").replace("<", "").replace(">", "").strip()


def cut_chars(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n].rstrip()


def cut_bytes(s: str, n: int) -> str:
    b = s.encode("utf-8")
    return s if len(b) <= n else b[:n].decode("utf-8", "ignore").rstrip()


def clean_tags(tags: List[str], limit: int = 480) -> List[str]:
    out, total, seen = [], 0, set()
    for t in tags:
        t = _strip(t).strip("#,; ")[:100]
        if not t or t.lower() in seen:
            continue
        cost = len(t) + (2 if " " in t else 0) + 1     # YouTube tính thêm dấu ngoặc kép với tag có khoảng trắng
        if total + cost > limit:
            break
        out.append(t)
        seen.add(t.lower())
        total += cost
    return out


def finalize(title: str, description: str, tags: List[str], is_short: bool) -> dict:
    title, desc = _strip(title), _strip(description)
    if is_short:
        if SHORTS.lower() not in title.lower():
            title = cut_chars(title, 100 - len(SHORTS) - 1) + " " + SHORTS
        if SHORTS.lower() not in desc.lower():
            desc = (desc + "\n\n" + SHORTS).strip()
    return {"title": cut_chars(title, 100), "description": cut_bytes(desc, 4900), "tags": clean_tags(tags)}
