# Studio Taysriul

Dashboard publikasi multi-platform untuk satu workspace. Foto dan video disimpan di PostgreSQL. Token bot dan URL webhook disimpan terenkripsi. Worker mengirim dari server walaupun browser ditutup. Tidak menggunakan Node.js, Redis atau sharp.

## Pasang lewat GitHub dan Coolify

1. Ekstrak ZIP lalu upload seluruh isi, termasuk folder templates, ke root repo GitHub baru.
2. Buat resource Application baru di Coolify dari repo. Pilih Docker Compose dengan lokasi /docker-compose.yaml.
3. Isi tiga environment variable runtime: APP_KEY, DB_PASSWORD dan ADMIN_PASSWORD. Untuk setiap nilai jalankan openssl rand -hex 32 secara terpisah. ADMIN_PASSWORD digunakan saat login. Simpan APP_KEY dan password database untuk redeploy dan pemulihan backup.
4. Pasang subdomain uji HTTPS pada service web dengan target port internal 8000, misalnya https://studio.taysriulqurani.id:8000 di kolom Domains Coolify. Arahkan DNS subdomain ke VPS. Buka alamat HTTPS biasa setelah deploy. Database memakai volume terpisah.
5. Login, pilih Akun Telegram, masukkan token bot dari BotFather dan @username channel atau ID numeriknya. Pastikan bot adalah admin dengan hak posting.
6. Uji pada channel privat milik sendiri. Jadwalkan satu foto lima menit ke depan, tutup browser, kemudian cek pesan dan tautan hasil di Kalender. Uji juga perubahan waktu dan pembatalan. Setelah lolos, pindahkan domain utama jika diinginkan.

## Perilaku operasional

Satu worker mengambil pekerjaan dengan penguncian database. Kegagalan jaringan setelah kirim menghasilkan status Periksa channel. Jika worker berhenti saat kirim, status dapat tertahan Mengirim. Periksa channel sebelum membuat kiriman pengganti untuk mencegah duplikasi. Jadwal yang sudah lewat diproses setelah worker aktif kembali. Agenda menampilkan maksimal 200 entri. Foto JPEG/PNG dan teks didukung. Dashboard memakai cookie Secure dan memerlukan HTTPS. Cadangkan volume PostgreSQL dan APP_KEY secara terpisah.

Lihat ROADMAP.md untuk 10 langkah pengembangan berikutnya.

## Memperbarui instalasi

Upload seluruh isi paket ke repo yang sudah dipakai, termasuk publishing.py, templates/ dan static/. Pertahankan APP_KEY, DB_PASSWORD, ADMIN_PASSWORD dan volume studio_db, lalu redeploy web dan worker dari commit yang sama. Pembaruan menambah tabel dan mengisi tipe akun lama sebagai Telegram saat startup. Cadangkan database sebelum pembaruan.

## Alur publikasi

1. Tambahkan ide pada Papan ide. Buka Edit atau pindahkan, pilih tahap Draf, lalu buka dari menu Draf.
2. Unggah JPEG atau PNG melalui Media atau langsung dari editor. Foto yang diunggah dapat digunakan lagi melalui pustaka.
3. Untuk Discord, buat webhook masuk pada channel teks server sendiri, lalu isi nama dan URL webhook di Akun sosial. Simpan token Telegram atau URL Discord hanya di dashboard.
4. Di editor pilih satu atau beberapa tujuan. Caption dan foto yang sama akan dikirim ke akun terpilih, dengan pemeriksaan batas panjang masing-masing. Pilih jam WIB atau kirim sekarang. Setiap tujuan mendapat satu baris di kalender. Simpan draf menyimpan isi dan foto; pilih kembali tujuan serta waktu saat membuka draf.
5. Jika respons penerbit tidak pasti, periksa channel sebelum mengirim ulang. Ringkasan menampilkan apakah worker baru-baru ini aktif.
6. Di Tautan, buat alamat /r/nama dan lihat jumlah akses. Angka ini mencakup permintaan dari bot dan pembaca pratinjau.

## Sambungkan akun dalam lima langkah

1. **Perbarui Stufio.** Deploy paket terbaru melalui Docker Compose. Pertahankan volume PostgreSQL dan APP_KEY lama. Isi `SOCIAL_ORIGIN` dengan domain HTTPS publik service web, misalnya `https://studio.example.com`, tanpa path.
2. **Siapkan aplikasi pengembang.** Isi pasangan variabel di bawah pada konfigurasi deploy. Di portal platform, daftarkan callback persis sebagai `<SOCIAL_ORIGIN>/akun/oauth/<slug>/callback`. Aktifkan produk, izin dan akun penguji yang diperlukan. Gunakan OAuth 2.0 Web App dengan client secret untuk X.
3. **Sambungkan Telegram dan Discord.** Di **Akun sosial**, masukkan token bot serta ID/username channel atau grup Telegram dengan bot sebagai admin. Untuk Discord, gunakan webhook masuk dari channel teks. Ulangi untuk tiap tujuan.
4. **Sambungkan akun OAuth.** Pilih platform, masuk di halaman resmi platform, lalu berikan izin. Untuk Meta, pilih aset yang ingin diotorisasi. Stufio menyimpan seluruh aset relevan yang dikembalikan oleh API. Ulangi dengan akun lain sesuai kebutuhan. Menyambungkan ulang identitas yang sama memperbarui koneksi lama.
5. **Periksa koneksi.** Pastikan akun muncul di daftar, lalu coba tambah akun ketiga dan sambungkan ulang salah satu akun. Token disimpan terenkripsi. Gunakan **Lepas dari Stufio** untuk menghapus koneksi OAuth lokal. Untuk mencabut izin di platform, gunakan pengaturan akun platform.

| Platform | Slug callback | Variabel lingkungan | Produk atau tipe akun |
|---|---|---|---|
| Instagram | `instagram` | `INSTAGRAM_CLIENT_ID`, `INSTAGRAM_CLIENT_SECRET` | Instagram API dengan Facebook Login untuk akun Business/Creator yang tertaut ke Halaman Facebook |
| Threads | `threads` | `THREADS_CLIENT_ID`, `THREADS_CLIENT_SECRET` | Threads API dengan izin `threads_basic` |
| Facebook | `facebook` | `FACEBOOK_CLIENT_ID`, `FACEBOOK_CLIENT_SECRET` | Facebook Login dan akses Pages |
| TikTok | `tiktok` | `TIKTOK_CLIENT_ID`, `TIKTOK_CLIENT_SECRET` | Login Kit untuk Web. Isi Client Key pada variabel `TIKTOK_CLIENT_ID` |
| LinkedIn | `linkedin` | `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET` | Sign In with LinkedIn using OpenID Connect untuk profil |
| YouTube | `youtube` | `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET` | OAuth client tipe Web dan YouTube Data API v3 |
| X | `x` | `X_CLIENT_ID`, `X_CLIENT_SECRET` | X API dengan akses profil pengguna |
| Pinterest | `pinterest` | `PINTEREST_CLIENT_ID`, `PINTEREST_CLIENT_SECRET` | Pinterest API dengan izin `user_accounts:read` |

Stufio tidak membatasi jumlah akun tersimpan. Akses API, persetujuan aplikasi, kuota, dan biaya tetap mengikuti platform. Delapan konektor OAuth memiliki adapter publikasi pada rilis ini; fitur dan ketersediaan aktual mengikuti izin API. Lihat UPDATE-MULTIPLATFORM.md untuk matriks dukungan, langkah migrasi dan pengujian. Untuk akun OAuth dengan masa aktif token yang diketahui, Stufio menampilkan status sambungkan ulang setelah token kedaluwarsa. Jika akses dicabut di platform, sambungkan ulang dari kartu platform.
