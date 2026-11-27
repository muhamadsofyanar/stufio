# Laporan perubahan dan hasil uji Stufio

## Audit ZIP awal

Sumber adalah stufio-main (3).zip. Web memakai Flask, template Jinja dan JavaScript langsung. PostgreSQL menyimpan kredensial terenkripsi dengan pgcrypto, aset biner, draf, dan antrean pengiriman. Web dan worker memakai image Python yang sama. Dalam versi awal akun dibedakan menurut channel/webhook atau pasangan platform dan ID eksternal, tetapi seluruh tabel bisnis dan login admin dipakai bersama. Dashboard belum mengenali anggota, workspace, komentar, atau laporan API. Terdapat adapter publikasi dan OAuth yang sudah dapat digunakan sebagai fondasi. Kode yang ada dipertahankan untuk publikasi dan aturan validasi format.

## Perubahan yang dapat digunakan

| Area | Implementasi |
|---|---|
| Workspace dan data lama | Registry workspace, tiga merek awal, pembuatan workspace tambahan, switcher, penggantian nama, schema PostgreSQL per workspace dan perlindungan formulir lama. Instalasi yang dimigrasikan mempertahankan schema awal sebagai Studio lama. |
| Akun dan OAuth | Daftar tujuan menurut workspace. Satu workspace dapat mempunyai beberapa akun platform yang sama. OAuth state sekali pakai, callback per sesi, token terenkripsi. Lepas koneksi Telegram/Discord membatalkan jadwal yang masih menunggu. Kiriman yang sudah mulai dikirim mungkin tetap sampai. |
| Konten | Editor multitujuan dengan caption khusus, pratinjau, draf persisten beserta pilihan tujuan dan opsi, pustaka JPEG/PNG/MP4, papan ide, kalender bulanan WIB, pengubahan waktu dan pembatalan jadwal. |
| Publikasi | Worker PostgreSQL memeriksa workspace bergiliran. Satu job per tujuan. Tautan media sementara dan tautan pendek mengandung identitas workspace. Tautan pendek lama tetap dilayani. Halaman Sudah terbit membaca hasil yang telah diterima worker. |
| Interaksi | Kotak masuk bersama untuk hasil sinkronisasi YouTube, Messenger, Instagram dan Threads. Filter status, balasan berdasarkan account ID dan ID pesan/komentar tersimpan. Percobaan pengiriman yang belum pasti tetap ditandai untuk diperiksa. |
| Analitik | Snapshot metrik akun yang tersedia melalui API YouTube, Instagram dan Facebook Page serta ekspor CSV. Angka hanya muncul sesudah sinkronisasi. |
| Akses | Admin utama, pengelola workspace, editor, dan pembaca. Pemeriksaan server mencakup operasi konten, pengaturan, akun, sinkronisasi, balasan, dan pergantian workspace. Kata sandi anggota di-hash. |
| UI | Navigasi dan identitas workspace, tampilan kalender, halaman tim, laporan dan inbox, penyesuaian responsif untuk halaman yang sudah ada. |
| Operasional | Compose utama tetap menggunakan volume studio_db. Tersedia overlay untuk akses localhost, panduan backup/restore, dan pengecualian secret/backup dari build context. |

## Hasil pengujian

| Pengujian | Lingkungan dan hasil |
|---|---|
| Backend dan adapter | **25 tes lulus** dengan PostgreSQL 16.16. Terdiri dari 17 tes sumber awal dan 8 tes integrasi tambahan. |
| Backup dan migrasi | Aplikasi asli membentuk skema uji, lalu diisi akun dengan kredensial terenkripsi, media, draf tertaut, antrean, dan tautan. Dump format custom dipulihkan ke database kosong. Migrasi berjalan saat aplikasi versi baru dibuka. Dekripsi, relasi draf-media, status antrean, URL lama, dan workspace kosong yang baru diverifikasi. Startup berulang terjadi ketika web dan worker dijalankan. |
| Instalasi bersih | Nama dan jumlah tiga workspace awal diverifikasi pada PostgreSQL 17.12. |
| Isolasi dan akses | Lookup aset dengan konteks workspace lama ditolak, draf terpisah, tanda tangan media tidak berlaku pada workspace lain, switch tanpa keanggotaan ditolak. Hak editor dan pembaca serta pencabutan akses diuji melalui route Flask. |
| Multi-akun dan penjadwalan | Tiga tujuan dalam satu pengajuan. Job masa depan ditahan, dua job dijadwalkan ulang dan dikirim melalui adapter simulasi, satu dibatalkan. Tujuan yang tidak valid membatalkan transaksi multitujuan. Caption khusus dan lepas akun ikut diuji. |
| OAuth dan publikasi | HTTP route login dan callback, penolakan replay/konteks berubah, penyimpanan akun dan status posting diuji. Pertukaran dengan provider menggunakan respons simulasi. Tidak ada kiriman eksternal dari tes ini. |
| Komentar dan analitik | Snapshot YouTube dan CSV, utas komentar, Messenger dan pencegahan balasan ganda, komentar dan balasan Instagram/Threads, serta snapshot Instagram diuji dengan respons API simulasi dan penyimpanan PostgreSQL. |
| Frontend | Kompilasi Python dan pemeriksaan sintaks composer.js lulus. Aplikasi tidak memiliki build Node. Chromium membuka 12 halaman sesudah login pada lebar 390, 768, dan 1440 px tanpa overflow horizontal halaman. Switcher dan penyimpanan draf diuji pada ketiga ukuran, perpindahan editor/pratinjau pada 390 px. |
| Runtime | Gunicorn, worker Python, dan PostgreSQL 16.16 berjalan bersama. Request browser berhasil dan heartbeat worker workspace terbaca. |
| Docker | Compose utama dan overlay localhost lolos validasi konfigurasi. Percobaan Compose up pada project uji terhalang izin socket daemon. Image build dan startup container belum terverifikasi. |

## Batas verifikasi dan cakupan

Tidak ada endpoint database produksi, volume lama, atau akun penguji platform yang disertakan dalam ZIP. Backup dan restore di atas menggunakan data uji. Instalasi produksi, OAuth live, penerbitan live, sinkronisasi live dan izin app review belum terverifikasi. Pengujian di staging membutuhkan target Compose yang dapat diakses dan akun/platform uji. Rahasia runtime disediakan di host atau secret manager.

Editor memakai satu media per kiriman. Carousel, thread berantai, polling, teks panjang Threads dan sinkronisasi webhook penuh belum diimplementasikan. Inbox memuat sebagian riwayat sesuai batas yang dijelaskan di README. Laporan berisi snapshot akun terakhir, belum menyimpan tren historis. Format, izin aplikasi, kuota dan keputusan moderasi masing-masing platform menentukan hasil live. TikTok saat ini mengunggah draf. Untuk status platform yang belum terkonfirmasi, cek akun tujuan sebelum mengirim ulang.
