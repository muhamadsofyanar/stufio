# Tahap 1. Fondasi workspace dan akun

Versi dasar Stufio c3f2b341. Taysriul memakai kembali workspace, keanggotaan, peran, login, konektor dan worker yang tersedia.

## Perubahan

- Akun tersimpan menampilkan platform, nama, ID tujuan dan status koneksi. Gunakan ID untuk membedakan akun senama.
- Akun OAuth yang dilepas mempertahankan identitas dan histori. Aplikasi menghapus isi kredensial lokal, membatalkan job menunggu dan mencatat tindakan. Sambung ulang dengan identitas provider yang sama memakai ID sebelumnya. Job yang telah mulai dikirim perlu diperiksa di platform.
- Akun yang mendukung sinkronisasi aktivitas menampilkan hasil terakhir dan waktu sukses terakhir. Kegagalan berikutnya mempertahankan waktu sukses sebelumnya. Editor, pengelola dan owner dapat memulai sinkronisasi. Pembaca hanya melihat hasil.
- Sidebar mengelompokkan Publikasi, Interaksi, Analitik dan Pengaturan. Riwayat administrasi menampilkan 50 perubahan terbaru di workspace terkait.
- Migrasi aditif saat startup membuat admin_events serta kolom active, synced_at dan sync_result pada oauth_accounts di setiap schema. Migrasi mempertahankan ID, kredensial dan metrik akun lama.
- Route yang diperbarui mencakup /akun, callback OAuth, lepas akun, /pengaturan, sinkronisasi aktivitas, balasan dan feed. Semua memakai URL lama.
- Berkas yang berubah: app.py, workspace_views.py, templates/accounts.html, templates/studio.html, templates/workspace.html, static/dialogs.js, static/studio.css, tests/test_workspaces.py dan README.md. Berkas tambahan: laporan ini.

## Verifikasi

Python 3.12 dan PostgreSQL 16.2, instalasi lokal terisolasi. Sebanyak 29 tes lulus, termasuk 27 tes lama serta regresi untuk pemutusan akun senama dan kegagalan sinkronisasi sesudah sukses. Migrasi dari skema versi ZIP mempertahankan satu akun uji dengan kredensial yang masih dapat didekripsi dan nilai metrik lama. Gunicorn melayani halaman login Taysriul. Sintaks kedua berkas JavaScript lulus pemeriksaan Node. API eksternal dalam tes memakai respons simulasi. Pengiriman nyata, izin provider, render visual lintas perangkat dan build Docker belum diverifikasi pada versi ini.

## Uji manual

1. Jalankan aplikasi dengan panduan README.md. Untuk akses localhost pakai overlay compose.local.yaml bersama docker-compose.yaml. Masuk sebagai admin.
2. Di Pengaturan, buat workspace dan tambahkan anggota. Periksa riwayat di workspace asal, lalu pindah memakai pemilih workspace. Login sebagai viewer untuk memeriksa pembatasan akses.
3. Hubungkan dua akun uji bernama sama. Bandingkan ID pada halaman Akun sosial. Sinkronkan aktivitas salah satu akun yang mendukungnya. Kembali ke halaman akun dan periksa hasil serta waktu sinkronisasi.
4. Jadwalkan satu post untuk tiap akun. Lepas satu akun sebelum jadwal tiba. Periksa status kedua job di kalender, riwayat metrik akun lama, dan catatan di pengaturan. Sambungkan akun yang sama kembali dan periksa jumlah koneksi.
