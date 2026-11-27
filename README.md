# Taysriul | Rilis publikasi, Tahap 1–4

Panduan perubahan dan pemeriksaan sebelum deploy tersedia di RILIS-PUBLIKASI.md.

Aplikasi Flask/Jinja untuk mengelola akun sosial, menulis draf, dan menjadwalkan publikasi per workspace. Gunicorn melayani web, PostgreSQL menyimpan media serta antrean, dan proses worker mengirim kiriman. Antarmuka berbahasa Indonesia dengan jadwal WIB.

## Memperbarui instalasi lama

Gunakan project Compose dan volume yang saat ini melayani Stufio. Pertahankan konfigurasi runtime, khususnya APP_KEY agar kredensial lama masih dapat didekripsi. ZIP sumber tidak memuat database produksi. Cadangkan dari instalasi aktif **sebelum** menjalankan web atau worker versi baru, karena keduanya menjalankan migrasi saat startup. Contoh pada host Linux dengan Compose dan PostgreSQL client sesuai versi server:

```sh
set -eu
umask 077
mkdir -p backups
backup="backups/stufio-$(date -u +%Y%m%dT%H%M%SZ).dump"
docker compose -f docker-compose.yaml exec -T db pg_dump -U studio -d studio -Fc > "$backup.tmp"
pg_restore --list "$backup.tmp" >/dev/null
mv "$backup.tmp" "$backup"
```

Simpan salinan dump dan APP_KEY di lokasi aman yang terpisah. Uji pemulihan memakai database kosong di host uji dengan `pg_restore --exit-on-error -d NAMA_DATABASE_UJI berkas.dump`. Setelah backup terverifikasi, deploy web dan worker dari versi yang sama. Untuk rollback, arahkan versi sebelumnya ke hasil restore yang terpisah dan rekonsiliasi kiriman setelah waktu backup sebelum menjalankan worker.

## Menjalankan

Pada instalasi baru, siapkan APP_KEY, DB_PASSWORD, ADMIN_PASSWORD melalui secret manager atau environment deploy. Gunakan nilai acak yang berbeda. Instalasi lama memakai nilai yang sudah terpasang.

```sh
docker compose -f docker-compose.yaml config --quiet
docker compose -f docker-compose.yaml up -d --build
docker compose -f docker-compose.yaml ps
docker compose -f docker-compose.yaml logs --tail=50 web worker
```

Di Coolify, arahkan domain HTTPS ke port internal 8000 pada web. Untuk preview di komputer sendiri, jalankan `docker compose -f docker-compose.yaml -f compose.local.yaml up -d --build` kemudian buka `http://localhost:8000`. Cookie sesi menggunakan Secure. Pada domain staging dan produksi gunakan HTTPS. Daftarkan SOCIAL_ORIGIN dan URL callback sesuai panduan konektor di bawah.

## Workspace, peran dan publikasi

- Instalasi baru membuat IzinHukum, StifinMulia dan Muhamad Sofyan. Saat migrasi, data lama tetap berada di **Studio lama**. Nama dapat diganti setelah pemiliknya ditentukan.
- Admin utama masuk dengan kolom nama pengguna kosong dan ADMIN_PASSWORD. Melalui **Tim & pengaturan** ia dapat membuat workspace, mendaftarkan pengguna, serta menetapkan akses. Kata sandi untuk pengguna baru minimal 12 karakter. Saat nama pengguna sudah ada, pemberian akses memakai identitas yang sama dan mempertahankan kata sandinya.
- Pengelola mengatur tim, nama workspace, dan koneksi akun. Editor mengelola konten, mengirim, menyinkronkan laporan dan membalas jika izin kanal tersedia. Pembaca dapat melihat konten serta mengekspor laporan. Server memeriksa keanggotaan dan peran pada setiap permintaan terlindungi.
- Pilih workspace di sidebar lalu **Pindah**. Pergantian memperbarui token formulir agar tab lama tidak mengirim data ke tujuan yang baru.
- Hubungkan akun melalui **Akun sosial**. Ulangi untuk akun tambahan. Buka **Buat post**, pilih akun, pilih atau unggah media, dan isi caption. Caption, pilihan akun, media, waktu, sampul, dan opsi YouTube dapat disimpan dalam draf. Caption khusus per akun menggantikan caption umum pada tujuan tersebut.
- Setiap tujuan mendapat job sendiri. Kalender WIB menampilkan jumlah per hari serta maksimal 200 detail dalam bulan terpilih. Worker mengunci job sebelum mengirim. **Sudah terbit** menampilkan hasil dengan status Terbit. Kiriman berstatus Diproses platform, Draf platform, atau Periksa channel dapat dilihat di kalender.
- Satu post mendukung satu JPEG/PNG atau MP4 sesuai batas kanal. Pustaka media mendukung penggunaan ulang. Papan ide serta tautan pendek tetap tersedia.
- Per workspace, akun, aset, job, draf, OAuth state, submissions, tautan dan aktivitas memiliki tabel PostgreSQL terpisah. Workspace awal memakai schema public untuk kompatibilitas. Workspace berikutnya memakai schema dengan ID internal. Registry workspace dan identitas pengguna berada di public. Worker dan callback memilih workspace di server. URL media publik ditandatangani bersama ID workspace dan waktu kedaluwarsa.

## Komentar, pesan, dan laporan

Kotak masuk menyinkronkan atas permintaan hingga 100 thread komentar terbaru per akun YouTube dan pesan terakhir dari maksimal 50 percakapan Messenger per Facebook Page. Data tersimpan per akun dan dapat ditinjau sesudah pengguna keluar. UI menampilkan hingga 300 item per tampilan. Instagram dan Threads memuat hingga 50 komentar atau balasan tingkat pertama dari masing-masing 10 postingan terbaru. Sinkronisasi belum mengambil seluruh riwayat maupun webhook. Waktu di kartu adalah waktu sinkronisasi.

Untuk komentar Instagram atau balasan Threads, aktifkan INSTAGRAM_COMMENTS_ENABLED=1 atau THREADS_COMMENTS_ENABLED=1 dan minta izin di dashboard developer. Dalam mode Instagram Unified tambahkan izin komentar pada konfigurasi login Meta. Sambungkan ulang akun. Untuk membalas komentar YouTube, aktifkan YOUTUBE_COMMENTS_ENABLED=1 dan sambungkan ulang akun dengan persetujuan youtube.force-ssl. Untuk Messenger aktifkan FACEBOOK_MESSENGER_ENABLED=1, siapkan izin pages_messaging di aplikasi Meta, dan sambungkan ulang Page. Pengiriman mengikuti batas waktu dan aturan platform. Balasan berstatus Periksa platform memerlukan verifikasi manual. Aplikasi mencatat percobaan sebelum pengiriman untuk mencegah pengulangan ketika respons jaringan terputus.

Laporan mengambil viewCount, subscriberCount yang ditampilkan kanal, dan videoCount dari YouTube. CSV memuat snapshot terakhir per akun. Instagram menyediakan followers_count dan media_count. Facebook Page menyediakan followers_count dan fan_count bila tersedia. Kanal lain belum memiliki pengambilan metrik di versi ini. Nomor pada dashboard publikasi berasal dari database antrean. Akun dengan token kedaluwarsa saat sinkronisasi mungkin perlu disambungkan ulang.

## Integrasi dan pengujian

Lihat [panduan adapter publikasi](UPDATE-MULTIPLATFORM.md), [catatan Instagram](UPDATE-INSTAGRAM.md), [laporan pengembangan dan pengujian](HASIL-UJI.md), serta [panduan pemasangan versi sebelumnya](PANDUAN-LAMA.md). Catatan rilis lama mendeskripsikan versi sebelum multi-workspace.

```sh
python -m unittest discover -s tests -v
python -m py_compile *.py
node --check static/composer.js
```

Untuk menjalankan juga pengujian PostgreSQL, siapkan **database khusus uji kosong** dengan pgcrypto, arahkan PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD ke sana, isi APP_KEY dan ADMIN_PASSWORD khusus uji, lalu jalankan `STUFIO_TEST_DATABASE=1 python -m unittest discover -s tests -v`. Suite membuat workspace dan data uji. Frontend memakai Jinja, CSS, dan JavaScript yang langsung dilayani Flask.

## Pembaruan antarmuka dan aktivitas

Akun sosial dan Tautan menggunakan dialog. Editor menampilkan satu pratinjau untuk setiap tujuan yang dipilih. Kalender mendukung filter akun. Komentar dan pesan Messenger memiliki pintu masuk terpisah, filter status, pencarian, dan pilihan akun. Laporan menyimpan nilai per akun dan metrik setiap hari ketika pengguna melakukan sinkronisasi. Sinkronisasi berikutnya pada tanggal WIB yang sama memperbarui nilai hari itu. Tanggal laporan memfilter riwayat. Snapshot terkini dan unduhan CSV tetap menampilkan hasil terakhir. Hari tanpa sinkronisasi tidak diberi nilai.

Feed Threads memerlukan THREADS_FEED_ENABLED=1, akses aplikasi ke threads_keyword_search, redeploy, dan penyambungan ulang akun. Pencarian menggunakan /keyword_search dengan TOP atau RECENT. Filter media diterapkan pada halaman hasil yang diterima. Tautan hasil membuka Threads untuk membalas. Dukungan pencarian topik khusus dan balasan feed langsung belum tersedia. Instagram DM dan undangan koneksi lintas perangkat belum tersedia.

Pemeriksaan versi ini menggunakan PostgreSQL 16 dan respons API simulasi. Route, isolasi workspace, pencarian/penyaringan aktivitas, upsert snapshot harian dan pencarian Threads termasuk dalam 27 tes otomatis. Integrasi live serta deployment Docker menunggu verifikasi staging.
