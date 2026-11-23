"""Tải video từ Google Drive về máy chạy GitHub Actions.

Thứ tự thử:
1. Drive API bằng service account (ổn định nhất, cần file được chia sẻ cho email service account
   hoặc để chế độ 'Bất kỳ ai có đường liên kết').
2. gdown (như tải bằng link công khai; xử lý trang xác nhận của file lớn).
Nếu Drive trả về trang HTML (hết lượt tải / chưa public) thì báo lỗi rõ ràng, không đăng nhầm file rác.
"""
import os


class DriveError(Exception):
    pass


def _ok(path: str) -> bool:
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return False
    with open(path, "rb") as f:
        head = f.read(512).lstrip().lower()
    return not (head.startswith(b"<!doctype html") or head.startswith(b"<html"))


def probe(creds, fid: str):
    """Kiểm tra service account có đọc được file không. Trả về (ok, thông báo)."""
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    try:
        svc = build("drive", "v3", credentials=creds, cache_discovery=False)
        meta = svc.files().get(fileId=fid, fields="name,size,mimeType", supportsAllDrives=True).execute()
        mb = int(meta.get("size", 0)) / 1_048_576
        return True, f"{meta.get('name')} ({mb:.1f} MB, {meta.get('mimeType')})"
    except HttpError as e:
        return False, f"Drive API {e.resp.status} (sẽ thử gdown khi đăng thật)"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def download(creds, fid: str, dest: str) -> int:
    """Tải file về dest, trả về số byte. Lỗi -> DriveError."""
    errs = []
    try:
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaIoBaseDownload
        svc = build("drive", "v3", credentials=creds, cache_discovery=False)
        req = svc.files().get_media(fileId=fid, supportsAllDrives=True)
        with open(dest, "wb") as f:
            dl, done = MediaIoBaseDownload(f, req, chunksize=32 * 1024 * 1024), False
            while not done:
                _, done = dl.next_chunk()
        if _ok(dest):
            return os.path.getsize(dest)
        errs.append("Drive API trả file rỗng/HTML")
    except Exception as e:  # noqa: BLE001
        status = getattr(getattr(e, "resp", None), "status", "")
        errs.append(f"Drive API {status or type(e).__name__}")

    try:
        import gdown
        if os.path.exists(dest):
            os.remove(dest)
        out = gdown.download(id=fid, output=dest, quiet=True)
        if out and _ok(dest):
            return os.path.getsize(dest)
        errs.append("gdown không tải được (link chưa để 'Bất kỳ ai có liên kết' hoặc Drive giới hạn lượt tải)")
    except Exception as e:  # noqa: BLE001
        errs.append(f"gdown: {e}")
    raise DriveError("; ".join(errs))
