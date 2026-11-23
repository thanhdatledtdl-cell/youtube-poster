"""Upload video lên YouTube (YouTube Data API v3, videos.insert, resumable).

Mỗi kênh dùng Client_ID/Client_Secret của dự án Google Cloud + Refresh_Token RIÊNG của kênh đó
(lấy từ tab API). Mỗi lần upload tốn ~1.600 đơn vị quota.
"""
import json
import random
import time

TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
QUOTA_REASONS = {"quotaExceeded", "dailyLimitExceeded", "uploadLimitExceeded"}


class QuotaError(Exception):
    """Hết quota/giới hạn upload trong ngày: dừng đường ống này, KHÔNG tính là lần thử lỗi của video."""


class AuthError(Exception):
    """Refresh token hỏng/hết hạn: lỗi của cả kênh, không đổ lỗi cho từng video."""


def _credentials(client_id, client_secret, refresh_token):
    from google.oauth2.credentials import Credentials
    return Credentials(None, refresh_token=refresh_token, token_uri=TOKEN_URI,
                       client_id=client_id, client_secret=client_secret, scopes=SCOPES)


def refresh_check(client_id, client_secret, refresh_token):
    """Thử đổi refresh token lấy access token. Trả về None nếu OK, hoặc chuỗi mô tả lỗi."""
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    try:
        _credentials(client_id, client_secret, refresh_token).refresh(Request())
        return None
    except RefreshError as e:
        return _auth_msg(e)
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}: {e}"


def _auth_msg(e) -> str:
    return (f"Refresh token không dùng được ({e}). Thường do: dự án OAuth còn ở chế độ 'Testing' "
            "(token hết hạn sau 7 ngày - hãy chuyển 'In production'), token bị thu hồi, "
            "hoặc dán nhầm Client_ID/Secret của dự án khác. Lấy lại token cho kênh này (HUONG_DAN mục 12).")


def build_client(client_id, client_secret, refresh_token):
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    creds = _credentials(client_id, client_secret, refresh_token)
    try:
        creds.refresh(Request())
    except RefreshError as e:
        raise AuthError(_auth_msg(e))
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def _reasons(err) -> list:
    try:
        j = json.loads(err.content.decode("utf-8", "ignore"))
        return [x.get("reason", "") for x in j.get("error", {}).get("errors", [])]
    except Exception:  # noqa: BLE001
        return []


def upload(yt, path, title, description, tags, category_id, privacy) -> str:
    """Upload và trả về ID video. Hết quota -> QuotaError. Lỗi khác -> ném nguyên ngoại lệ."""
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload
    body = {
        "snippet": {"title": title, "description": description, "tags": tags, "categoryId": str(int(category_id))},
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
    }
    media = MediaFileUpload(path, chunksize=16 * 1024 * 1024, resumable=True, mimetype="video/*")
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    response, tries = None, 0
    while response is None:
        try:
            _, response = req.next_chunk()
        except HttpError as e:
            if set(_reasons(e)) & QUOTA_REASONS:
                raise QuotaError(f"YouTube báo hết quota/giới hạn upload: {','.join(_reasons(e))}")
            if e.resp.status in (500, 502, 503, 504) and tries < 5:
                tries += 1
                time.sleep(2 ** tries + random.random())
                continue
            raise
        except (ConnectionError, TimeoutError) as e:
            if tries >= 5:
                raise
            tries += 1
            time.sleep(2 ** tries + random.random())
    if "id" not in response:
        raise RuntimeError(f"YouTube không trả ID video: {response}")
    return response["id"]
