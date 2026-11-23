# Đăng YouTube tự động bằng GitHub Actions (thay n8n)

Google Sheet vẫn là **bảng điều khiển** (CONFIG, API, GEMINI_KEYS, PROMPT, các tab Kenh_X…).
Repo này chỉ thay phần **"động cơ đăng"** mà n8n đang làm: tải video từ Drive → Gemini điền tiêu đề/mô tả/tag → upload YouTube → ghi kết quả vào Sheet.

Giữ nguyên **không đổi** các script Apps Script hiện có (phân bổ video, báo cáo Telegram, reset key Gemini): repo này ghi vào Sheet đúng định dạng n8n đã ghi nên chúng chạy tiếp bình thường.

```
Apps Script (giữ nguyên)  ──ghi──▶  Sheet  ◀──đọc/ghi──  GitHub Actions (repo này)  ──upload──▶  YouTube
 phân bổ · Telegram · reset key                              lọc giờ · quota · Gemini · Drive
```

---

## ⚠️ Đọc trước khi thử trên bản sao Sheet

Bản sao Sheet **dùng chung** token YouTube, dự án Google Cloud và các link Drive với Sheet gốc (n8n vẫn đang chạy trên Sheet gốc). Vì vậy:

1. **Chỉ thử với 1–2 video test riêng**, *không nằm trong hàng đợi `Cho_dang` của Sheet gốc*. Nếu không, cùng một video sẽ bị đăng 2 lần (1 lần từ bản sao, 1 lần từ n8n).
2. Trong bản sao, đổi các dòng `Cho_dang` khác sang `Nhap` (hoặc xóa) để chỉ còn đúng dòng test.
3. **Không chạy `Cài lịch tự chạy mỗi giờ` / `installTrigger` / `tgCaiDat` trong bản sao** (trigger không tự sao chép sang bản sao, đừng cài lại). Nếu cài, bản sao sẽ tự phân bổ thêm video từ sheet nguồn và Telegram báo trùng.
4. Luôn chạy thử với `privacy = private`, đăng xong vào YouTube Studio xóa video test.
5. Quota YouTube tính theo **dự án Google Cloud**, mà bản sao không thấy lượt n8n đã dùng. Cột `Quota_con_lai` trong bản sao có thể cao hơn thực tế. Một video thử thì không sao.
6. Đặt múi giờ Sheet là **(GMT+07:00) Hồ Chí Minh**: *Tệp → Cài đặt → Múi giờ*.

---

## Cài đặt (làm 1 lần, khoảng 15 phút)

### Bước 1 – Tạo service account để repo đọc/ghi Sheet
1. Vào [Google Cloud Console](https://console.cloud.google.com), chọn (hoặc tạo) một dự án. Dự án nào cũng được, không cần trùng dự án YouTube.
2. **APIs & Services → Library**: bật **Google Sheets API** và **Google Drive API**.
3. **IAM & Admin → Service Accounts → Create**. Đặt tên, ví dụ `youtube-poster`. Không cần gán role.
4. Mở service account vừa tạo → tab **Keys → Add key → Create new key → JSON**. Tải file JSON về (giữ kín, **không đưa vào repo**).
5. Mở **bản sao Google Sheet** → *Chia sẻ* → dán email của service account (dạng `…@…iam.gserviceaccount.com`, nằm trong file JSON ở trường `client_email`) → quyền **Người chỉnh sửa**.
6. (Khuyến nghị) Chia sẻ thư mục Drive chứa video cho email này với quyền **Người xem**. Nếu không, repo vẫn thử tải theo link công khai.

### Bước 2 – Tạo repo và đưa code lên
1. GitHub → **New repository** → đặt tên (vd `youtube-poster`), chọn **Private**.
2. Giải nén file zip này, đưa toàn bộ nội dung lên repo (kéo thả trên web hoặc `git push`). Giữ nguyên thư mục `.github/workflows/`.

### Bước 3 – Khai báo bí mật
Repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Tên secret | Giá trị |
|---|---|
| `SHEET_ID` | Đoạn giữa `/d/` và `/edit` trong URL bản sao Sheet (dán cả URL cũng được) |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | **Toàn bộ nội dung** file JSON ở bước 1 |

### Bước 4 – Chạy thử theo 3 mức (từ an toàn đến thật)
Repo → tab **Actions → dang-youtube → Run workflow**.

| Lần | Chọn `mode` | Mục đích | Có đăng / có ghi Sheet không |
|---|---|---|---|
| 1 | `doctor` | Kiểm tra tab, cột, token YouTube, quota, quyền đọc Drive | Không |
| 2 | `dry-run` | In ra sẽ đăng video nào, privacy gì | Không |
| 3 | `run` | **Đăng thật 1 video** | Có |

Với lần 2 và 3, đặt `pipelines` = ID đường ống cần thử (vd `A_NGAN`), `force` = ✔, `max_videos` = 1, `privacy` = **private**.

Sau lần `run`, kiểm tra trên Sheet bản sao:
- [ ] Dòng video: `Trang_thai_dang = Done`, có `Link_Youtube_video`, `Thoi_gian_dang_video`, `Tieu_de_youtube`/`Mo_ta_youtube`/`The_tag` đã điền, `Loi` trống.
- [ ] Tab THEO_DOI có thêm 1 dòng: `Ket_qua = Done`, `Quota_cost = 1600`, `Ngay_quota` dạng `20261120`, đúng `Du_an`.
- [ ] Tab API: `Quota_da_dung` tăng 1600 (công thức tự tính).
- [ ] Tab GEMINI_KEYS: 1 key tăng `Da_dung_hom_nay` (nếu video thiếu tiêu đề/mô tả/tag).
- [ ] Video Ngắn có `#Shorts` trong tiêu đề và mô tả.
- [ ] Video hiện trong YouTube Studio ở chế độ riêng tư. Sau đó xóa video test.

Xem chi tiết từng bước tại tab **Actions → lần chạy → job `post`**, và bảng tổng kết ở cuối trang lần chạy.

---

## Thêm kênh mới

Chỉ làm trên Sheet và Google Cloud, **không cần sửa code**.

### A. Lấy Refresh Token cho kênh (mỗi kênh một token riêng)
1. Google Cloud Console (dự án YouTube) → **APIs & Services → Library**: bật **YouTube Data API v3**.
2. **OAuth consent screen**: loại *External*, thêm email chủ kênh vào *Test users*. **Chuyển trạng thái sang "In production"**. Nếu để "Testing", refresh token hết hạn sau 7 ngày và đăng sẽ báo lỗi.
3. **Credentials → Create credentials → OAuth client ID** loại *Web application*, thêm *Authorized redirect URI*: `https://developers.google.com/oauthplayground`. Ghi lại **Client ID** và **Client Secret** (kênh cùng dự án dùng chung được).
4. Mở [OAuth 2.0 Playground](https://developers.google.com/oauthplayground) → bánh răng ⚙ → tick **Use your own OAuth credentials** → dán Client ID/Secret.
5. Ở Step 1 nhập scope `https://www.googleapis.com/auth/youtube.upload` → **Authorize APIs** → đăng nhập bằng **tài khoản chủ kênh**. Nếu tài khoản có nhiều kênh, màn hình sẽ hỏi chọn kênh. **Chọn đúng kênh cần đăng.** Màn hình cảnh báo "app chưa xác minh" thì bấm *Nâng cao → Tiếp tục*.
6. Step 2 → **Exchange authorization code for tokens** → copy **Refresh token**.

### B. Khai báo trên Sheet
1. **Tab video:** copy `Kenh_A_Dai` và `Kenh_A_Ngan` → đổi tên thành `Kenh_X_Dai` và `Kenh_X_Ngan` → xóa dữ liệu, **giữ nguyên dòng tiêu đề**.
2. **Tab API:** thêm dòng mới: `API_name` (vd `YT_X`), `Loai = youtube`, Client_ID, Client_Secret, **Refresh_Token mới**, `Du_an` (cùng dự án thì ghi cùng tên), `Quota_toi_da = 10000`, `Trang_thai = OK`. Công thức `Quota_da_dung`/`Quota_con_lai` copy từ dòng bên trên xuống.
3. **Tab CONFIG:** thêm 2 dòng `X_DAI` và `X_NGAN` (copy từ dòng kênh khác rồi sửa):
   `Kenh`, `Loai` (Dai/Ngan), `Tab_du_lieu` (đúng tên tab), `API_name = YT_X`, `Prompt_name`, `So_video`, `Category_id`, `Privacy`, `Loai_Den_Nguon` (loại đèn để script phân bổ cấp video), `Active = TRUE`.
   Để lệch giờ giữa các kênh/loại, đặt `Gio_dang` khác nhau (vd kênh X dài `09:00,15:00`, ngắn `12:00,18:00`).
4. **Video thử:** dán 1 dòng vào tab video: `Tieu_de_video`, `Link_bai_dang_video` (link Drive "Bất kỳ ai có đường liên kết"), `Trang_thai_dang = Cho_dang`.

### C. Thử kênh mới
Chạy lần lượt `doctor` → `dry-run` → `run` với `pipelines = X_NGAN`, `privacy = private` (như Bước 4). Đăng được thì đổi `Privacy` trong CONFIG sang `public`.
Nếu kênh mới ở **dự án Google Cloud khác**, Client_ID/Secret và `Du_an` phải là của dự án đó.

---

## Quy tắc hoạt động (giống n8n)

- **Giờ đăng:** `Gio_dang` giờ VN. Hỗ trợ `07:00,11:00` và `06:00-21:00/3`, trống = mỗi giờ. Chỉ đăng khi giờ chạy nằm trong ±`TOLERANCE_PHUT` quanh một khung giờ, và chưa có video nào đăng trong khung đó (chống đăng trùng).
- **Số video mỗi lần:** `min(So_video, Quota_con_lai ÷ QUOTA_MOI_VIDEO)`. Hết quota thì bỏ qua đường ống đó.
- **Chọn video:** từ trên xuống, dòng `Cho_dang`. Dòng `Dang_xu_ly` kẹt quá `LOCK_PHUT` phút sẽ được xử lý lại (tính 1 lần thử).
- **Lỗi:** cộng `So_lan_thu`. Dưới `MAX_LOI` thì về `Cho_dang` thử lại lần sau, đủ `MAX_LOI` thì thành `Loi` (script Telegram sẽ báo). Lỗi trước bước upload (Gemini, Drive) không tính quota.
- **Hết quota YouTube** (`quotaExceeded`): trả dòng về `Cho_dang`, **không** tính lần thử, dừng đường ống đó.
- **Refresh token hỏng:** báo lỗi token cho cả kênh, **không** đốt lần thử của từng video.
- **Gemini:** chỉ gọi khi thiếu tiêu đề/mô tả/tag; ô đã có giữ nguyên. Xoay key, tự đánh `Error` key lỗi (key lỗi vĩnh viễn gắn `[MODEL]`, script reset bên Apps Script sẽ không tự bật lại).
- **Loai = Ngan:** tự thêm `#Shorts` vào tiêu đề và mô tả.
- **Telegram:** động cơ không gửi Telegram. Script Apps Script `tgCanhBaoLoi` (mỗi 10 phút) đã đọc lỗi từ Sheet và báo.

---

## Lỗi thường gặp

| Thông báo | Cách xử lý |
|---|---|
| `Không mở được Sheet…` | Chia sẻ Sheet cho email service account (Người chỉnh sửa); kiểm tra `SHEET_ID`. |
| `Google Sheets API has not been used…` | Bật *Google Sheets API* và *Google Drive API* trong dự án của service account. |
| `Refresh token không dùng được (invalid_grant)` | OAuth đang ở *Testing* (hết hạn 7 ngày) → chuyển *In production*, lấy lại token. Hoặc dán nhầm Client_ID/Secret của dự án khác. |
| `[tải Drive] … gdown không tải được` | Link chưa để "Bất kỳ ai có liên kết", hoặc Drive giới hạn lượt tải. Chia sẻ thư mục cho email service account. |
| `HẾT QUOTA` ở đường ống | Mỗi dự án chỉ ~6 video/ngày. Dùng thêm dự án Google Cloud hoặc xin tăng quota. |
| Video lên nhưng ở chế độ **private** dù CONFIG ghi public | Dự án chưa được YouTube audit: YouTube ép private. Cần gửi form audit. |
| `uploadLimitExceeded` | Kênh bị giới hạn số video upload mỗi ngày (thường kênh mới/chưa xác minh). Chờ sang ngày hoặc xác minh kênh bằng số điện thoại. |
| Lịch tự chạy mà không đăng gì | `TOLERANCE_PHUT` quá nhỏ (đặt 25), hoặc `Gio_dang` sai cú pháp: chạy `doctor`. |
| Job bị hủy giữa chừng khi đang upload | Dòng sẽ kẹt `Dang_xu_ly` rồi tự thử lại sau `LOCK_PHUT` phút. Có thể video đã lên YouTube một phần: kiểm tra YouTube Studio và xóa bản trùng nếu có. |

---

## Giai đoạn 2 (làm sau khi thử ổn)

1. Trong `.github/workflows/post.yml` bỏ dấu `#` ở 2 dòng `schedule` / `cron` để chạy mỗi giờ.
2. Đặt `TOLERANCE_PHUT = 25` trong tab HE_THONG (cron của GitHub thường trễ 5–30 phút).
3. Lưu ý phút chạy: repo **private** gói Free có 2.000 phút/tháng; chạy mỗi giờ không có việc cũng tốn ~1 phút/lần. Repo public không giới hạn phút nhưng log công khai. Có thể để Apps Script chỉ gọi GitHub khi có kênh đến giờ để tiết kiệm (xem hướng dẫn riêng).
4. Chạy song song với n8n bằng cách **tắt (Active = FALSE) dần từng kênh bên Sheet gốc** rồi bật bên Sheet chạy GitHub, tránh hai bên cùng đăng một kênh.

## Chạy test trên máy

```bash
pip install -r requirements.txt pytest
python -m pytest -q
```
