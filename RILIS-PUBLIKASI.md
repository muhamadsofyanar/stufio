# Rilis publikasi Taysriul
Basis rilis adalah commit 03891cdce809a929f94fdf217e8e7fb0fd2557da, sama dengan sumber deployment Coolify pada 27 November 2026. Paket memuat aplikasi lengkap, termasuk Tahap 1.

| Tahap | Perubahan dan cara menguji |
|---|---|
| 2 | Pada Buat post pilih dua akun. Tentukan caption dan media pustaka masing-masing, atau pilih tanpa media. Periksa pratinjau, simpan draf, lalu buka kembali. Kiriman yang dibuat dengan versi ini dapat disalin menjadi draf baru melalui kalender atau daftar kiriman. |
| 3 | Pada Pengaturan aktifkan persetujuan workspace. Kirim materi, lalu buka Draf. Owner atau manager dapat meminta revisi dengan catatan atau menyetujui. Editor dapat memperbaiki lalu mengajukan ulang. Worker hanya mengambil job terjadwal. Saat persetujuan dinonaktifkan, materi baru langsung dijadwalkan. Materi yang telah diajukan tetap perlu ditinjau. Pada Kalender, pilih bulan atau tanggal dalam minggu dan filter akun. Klik tanggal untuk membuka editor dengan waktu awal 09.00 WIB. |
| 4 | Di editor, pilih tujuan lalu buka Impor banyak materi. CSV UTF-8 memakai header caption,due,asset. Satu baris mewakili satu materi untuk semua akun yang dipilih. Waktu dalam WIB; waktu kosong berarti segera setelah antrean atau persetujuan. Kolom asset berisi ID pustaka pada workspace aktif, atau kosong untuk teks. Maksimal 100 baris dan 500 KB. Format dan izin tiap platform tetap berlaku. Kesalahan satu baris membatalkan seluruh impor. Buka Log pengiriman pada kiriman. Tombol ulang hanya tersedia untuk tujuan berstatus Gagal. Status Periksa channel perlu rekonsiliasi manual. |

## Kode, database dan route

app.py mengatur migrasi, draf, variasi per tujuan, penjadwalan, keputusan peninjau, impor transaksional dan worker. workspace_views.py menyimpan pengaturan persetujuan. UI berubah pada templates/composer.html, editorial.html, workspace.html, studio.html dan static/composer.js. Pengujian regresi ditambahkan pada tests/test_workspaces.py. Berkas baru adalah laporan ini dan hasil tes.

Route POST baru adalah /editorial/<id>/copy dan /editorial/<id>/review. Route /buat menerima aksi bulk, /posts/<id> menerima retry dan /kalender menerima parameter week. Route /pengaturan menyimpan kebijakan per workspace.

Migrasi menambahkan public.workspace_migrations, tabel editorial_settings, editorial_history, job_events serta kolom posts.editorial_id. Perubahan tercatat per workspace dalam transaksi. Persetujuan secara default nonaktif. Draf dan job sebelumnya tetap dapat digunakan. Riwayat percobaan dan relasi materi editorial mulai dicatat pada versi ini.

## Pemeriksaan rilis

31 tes lulus pada PostgreSQL 16.2. Skenario baru memeriksa media/caption per tujuan, revisi hingga persetujuan, keputusan ganda, kalender mingguan, penyalinan materi, rollback impor, replay nonce, pengiriman dan retry satu tujuan. Log mentah tersedia di HASIL-UJI-PUBLIKASI.txt. Pada database uji dari versi yang terpasang, web dan worker baru dimulai bersama. HTTP GET /login berhasil; heartbeat terdeteksi pada ketiga workspace. Draf, jadwal, dan kemampuan dekripsi token lama tetap berfungsi.

## Deploy satu kali

Cadangkan database sesuai README dan simpan APP_KEY instalasi. Masukkan isi folder taysriul dari ZIP ke root repository aplikasi. Pertahankan volume database dan variabel Coolify yang sudah digunakan. Deploy web dan worker dari commit yang sama. Setelah deploy, buka /login, masuk, periksa indikator penjadwal di Ringkasan, lalu lakukan pengujian akun uji. Pengujian rilis ini memakai respons provider simulasi. Pengiriman ke akun nyata, tampilan visual lintas perangkat dan build Docker produksi belum diuji pada versi ini.
