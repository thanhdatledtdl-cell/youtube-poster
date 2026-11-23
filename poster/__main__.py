"""Dùng:
  python -m poster doctor [--pipelines A_NGAN]
  python -m poster run    [--pipelines A_NGAN,B_DAI] [--force] [--dry-run] [--max-videos 1] [--privacy private]

Biến môi trường bắt buộc:
  SHEET_ID                      ID (hoặc cả URL) của Google Sheet
  GOOGLE_SERVICE_ACCOUNT_JSON   nội dung file JSON key của service account
"""
import argparse
import json
import os
import re
import sys


def open_book():
    from .sheet import GSheetBook, SheetError
    raw_id = os.environ.get("SHEET_ID", "").strip()
    raw_sa = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw_id or not raw_sa:
        sys.exit("Thiếu biến môi trường SHEET_ID hoặc GOOGLE_SERVICE_ACCOUNT_JSON "
                 "(đặt trong GitHub: Settings > Secrets and variables > Actions).")
    m = re.search(r"/d/([A-Za-z0-9_-]+)", raw_id)
    sheet_id = m.group(1) if m else raw_id
    try:
        sa = json.loads(raw_sa)
    except json.JSONDecodeError:
        sys.exit("GOOGLE_SERVICE_ACCOUNT_JSON không phải JSON hợp lệ: hãy dán NGUYÊN nội dung file key.")
    try:
        return GSheetBook(sheet_id, sa)
    except SheetError as e:
        sys.exit(f"❌ {e}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="poster", description="Đăng YouTube tự động từ Google Sheet")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "doctor"):
        sp = sub.add_parser(name)
        sp.add_argument("--pipelines", default="", help="ID đường ống, cách nhau dấu phẩy (vd A_NGAN,B_DAI). Trống = tất cả")
    r = sub.choices["run"]
    r.add_argument("--force", action="store_true", help="bỏ qua lọc giờ Gio_dang (dùng khi chạy thử)")
    r.add_argument("--dry-run", action="store_true", help="chỉ in ra sẽ đăng gì, không ghi Sheet, không đăng")
    r.add_argument("--max-videos", type=int, default=None, help="giới hạn số video mỗi đường ống")
    r.add_argument("--privacy", choices=["public", "unlisted", "private"], default=None,
                   help="ép chế độ riêng tư, bỏ qua cột Privacy trong CONFIG")
    a = ap.parse_args(argv)

    only = [x for x in a.pipelines.split(",") if x.strip()]
    book = open_book()
    if a.cmd == "doctor":
        from .doctor import run_doctor
        return 0 if run_doctor(book, book.creds, only) else 1

    from .runner import Runner
    Runner(book, creds=book.creds, dry_run=a.dry_run, force=a.force, only=only,
           max_videos=a.max_videos, privacy=a.privacy).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
