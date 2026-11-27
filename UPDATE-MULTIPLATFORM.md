# Stufio Multi-Platform Publishing — panduan pembaruan

Paket ini berasal dari source e8b025534dbd6ea2e117da3a904505723efe67fd. Tidak berisi token, password, APP_KEY, atau file .env. Semua file dalam ZIP berada langsung di root repository.

## Lima langkah deployment

1. **Backup** database PostgreSQL melalui Coolify (volume studio_db). Catat APP_KEY yang sedang digunakan; jangan diubah. Jangan hapus volume atau buat database baru.
2. Ekstrak ZIP. Buka repository muhamadsofyanar/stufio, branch main. Upload semua isi folder hasil ekstrak ke root repo (termasuk subfolder templates, static, tests), menggantikan file yang sama. Commit perubahan. Jangan upload ZIP sebagai file tunggal.
3. Periksa ENV yang sudah ada di Coolify. Pertahankan DB_PASSWORD, APP_KEY, ADMIN_PASSWORD dan semua ID/secret yang sudah benar. SOCIAL_ORIGIN=https://taysriulqurani.id. Tambahkan INSTAGRAM_LOGIN_MODE=facebook (default) atau direct sesuai metode Meta di bawah. Worker otomatis menerima ENV OAuth yang sama dengan web.
4. Redeploy. Periksa log web, worker, dan database. Migrasi menambah kolom pada tabel yang sudah ada, tidak menghapus tabel/koneksi lama. Status akun OAuth lama menjadi "Sambungkan ulang untuk izin publikasi" sampai proses OAuth dengan scope baru berhasil.
5. Sambungkan ulang satu platform pada satu waktu. Mulai dari Facebook Page. Buat kiriman teks uji di Page uji yang Anda kelola dan periksa hasil di Kalender dan platform. Lanjutkan foto, video, dan satu kiriman terjadwal. Jangan menguji konten penting langsung.

## Dukungan adapter

| Platform | Teks | Foto | MP4 | Pengaturan |
|---|---|---|---|---|
| Telegram | Ya | Ya | Ya | Bot admin |
| Discord | Ya | Ya | Ya | Webhook; batas media 8 MB |
| Facebook Page | Ya | Ya | Ya | pages_manage_posts; video diproses platform |
| Instagram | Caption | JPEG | Reels | Professional; URL media HTTPS publik sementara |
| Threads | Ya | Ya | Ya | threads_content_publish |
| YouTube | Judul + deskripsi | Tidak | Ya | Pilih visibilitas dan audiens; app belum diaudit mungkin hanya private |
| TikTok | Caption manual | Tidak | Draf video | video.upload; lanjutkan di notifikasi TikTok, bukan direct publish |
| LinkedIn | Ya | Ya | Ya | Personal member; w_member_social; versi API 202609 |
| X | Ya | Ya (5 MB) | Ya | tweet.write, media.write, offline.access; akses/paket API |
| Pinterest | Deskripsi | Ya | Ya | Pilih board; video membutuhkan cover foto pustaka |

Batas Stufio: satu media per kiriman, JPEG/PNG maksimum 8 MB, MP4 maksimum 32 MB. Platform dapat menerapkan batas resolusi, durasi, codec, teks, akses, persetujuan, dan kuota yang lebih ketat. Semua adapter belum diuji live dengan akun produksi. TikTok Direct Post, photo post TikTok, carousel, dan pemilihan thumbnail YouTube belum tersedia. TikTok draft tidak mengirim caption; isi kembali saat menyelesaikan draft. Riwayat status "Diproses platform" berarti upload diterima, bukan konfirmasi tayang; cek platform. Draft menyimpan media/caption tetapi tujuan dan opsi publikasi harus dipilih ketika membuka kembali.

## Facebook dan Instagram

Facebook: Meta App stufio2 harus memiliki pages_show_list, pages_read_engagement, business_management, pages_manage_posts. Tambahkan Ready for testing atau Advanced Access sesuai kebutuhan. Hubungkan ulang setelah upgrade.

Untuk error Invalid Scopes: instagram_basic, ada dua mode:
- facebook: pakai Instagram API with Facebook Login, Instagram Professional terkait Page, scope instagram_basic dan instagram_content_publish. Credentials dapat sama dengan Facebook jika Meta App memang mendukung use case Instagram.
- direct: gunakan Instagram API with Instagram Login, scope instagram_business_basic dan instagram_business_content_publishing. INSTAGRAM_LOGIN_MODE=direct dan INSTAGRAM_CLIENT_ID/SECRET dari pengaturan Instagram Login (bukan kredensial Facebook App jika nilainya berbeda). Daftarkan callback yang sama. Tambahkan akun profesional sebagai tester jika masih dalam pengujian. Jangan mengganti FACEBOOK_CLIENT_ID/SECRET.

## ENV dan callback

Setiap platform menggunakan pasangan PLATFORM_CLIENT_ID / PLATFORM_CLIENT_SECRET; isi melalui Coolify, bukan GitHub. Callback dihitung dari SOCIAL_ORIGIN + /akun/oauth/<slug>/callback.

| Slug | Callback |
|---|---|
| facebook | https://taysriulqurani.id/akun/oauth/facebook/callback |
| instagram | https://taysriulqurani.id/akun/oauth/instagram/callback |
| threads | https://taysriulqurani.id/akun/oauth/threads/callback |
| youtube | https://taysriulqurani.id/akun/oauth/youtube/callback |
| tiktok | https://taysriulqurani.id/akun/oauth/tiktok/callback |
| linkedin | https://taysriulqurani.id/akun/oauth/linkedin/callback |
| x | https://taysriulqurani.id/akun/oauth/x/callback |
| pinterest | https://taysriulqurani.id/akun/oauth/pinterest/callback |

Aktifkan API dan izin publikasi pada masing-masing portal developer. Untuk YouTube, aktifkan YouTube Data API v3, konfigurasi OAuth web app, dan beri izin youtube.upload; tambahkan test users jika belum dipublikasikan. TikTok memakai Content Posting API Upload (video.upload). LinkedIn perlu produk Sign In dengan OpenID Connect dan Share on LinkedIn. Pinterest membutuhkan board dan scope pins:read/pins:write. X harus menggunakan OAuth 2.0 web confidential app serta akses tulis/media. Untuk Threads, gunakan Threads App ID dan Secret yang sesuai.

## Worker dan keamanan

- Antrean menggunakan PostgreSQL; satu record per tujuan; worker tetap berjalan tanpa browser.
- Token akun OAuth terenkripsi di DB, tidak disalin ke GitHub atau URL media.
- Instagram/Threads/Pinterest cover menggunakan URL bertanda tangan dengan masa berlaku satu jam. Link ini diberikan ke platform hanya saat worker mengirim.
- Akses token yang mendukung refresh token dapat diperbarui oleh worker sebelum pengiriman. Platform yang tidak mengembalikan refresh token harus disambungkan ulang sebelum expiry.
- Kiriman dengan respons API tidak pasti diberi status Periksa channel; tidak otomatis dikirim ulang untuk mencegah duplikasi. Worker yang terhenti saat mengirim ditandai perlu diperiksa setelah 30 menit. Periksa platform sebelum mencoba kembali.
- Worker pemrosesan media dapat menunda antrean berikutnya. Beberapa status upload memerlukan pemeriksaan manual di platform.
- Upgrade menambah kolom tanpa menghapus data; rollback kode lama setelah kiriman OAuth baru dibuat tidak dianjurkan tanpa backup, karena kode lama tidak memahami job baru.

## Verifikasi lokal

```bash
python -m unittest discover -s tests -v
python -m py_compile *.py
node --check static/composer.js
```

12 pengujian simulasi telah lulus (payload, media, response dan scope), syntax Python/JavaScript serta Compose YAML diperiksa. Belum ada pengujian PostgreSQL nyata, Docker build maupun live API dari lingkungan pengembangan ini; lakukan checklist deployment sebelum produksi.

## Referensi API

- https://developers.facebook.com/docs/instagram-platform/
- https://developers.facebook.com/docs/threads/
- https://developers.google.com/youtube/data/reference/rest/v3/videos/insert
- https://developers.tiktok.com/docs/en/content-posting-api-reference-upload-video
- https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api
- https://docs.x.com/x-api/media/quickstart/media-upload-chunked
- https://developers.pinterest.com/docs/work-with-organic-content-and-users/create-boards-and-pins/
