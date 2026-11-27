# Rilis gabungan Tahap 5 dan 6

Basis sumber: muhamadsofyanar/stufio, commit 7baa88444e67fa382ace3cb2e0b13905ec7c61f8. Paket lengkap untuk satu deployment web dan worker.

## Tahap 5
- Komentar menampilkan akun dan referensi postingan jika disediakan provider. Tindak lanjut bisa ditandai selesai atau dibuka kembali dan difilter. Feed Threads yang telah ada tetap memakai izin provider, filter akun dan pencarian kata kunci.
- Inbox & layanan menampilkan daftar percakapan Messenger dan riwayat utas, identitas kontak, Page penerima, pencarian isi pesan/kontak/tag dan filter akun/status. Lampiran masuk dapat dibuka bila provider memberi URL HTTPS. Balasan keluar mendukung teks dan pilihan jawaban tersimpan.
- Sinkronisasi dipicu manual, 50 utas per halaman dan 50 pesan awal per utas. Gunakan Ambil percakapan berikutnya atau Muat pesan sebelumnya ketika provider memberikan kursor. Data yang sudah diambil tetap tersimpan. Pesan masuk baru dengan waktu setelah percakapan diselesaikan membukanya kembali saat disinkronkan. Pengulangan sinkronisasi dan pemuatan pesan lama tidak membuka kembali percakapan.
- Data aktivitas lama tetap dapat diakses di /aktivitas/inbox?stream=messages. Sinkronkan Page untuk mengisi inbox berutas menggunakan ID asli dari provider. Riwayat yang tidak dikembalikan oleh provider tidak direkonstruksi.

## Tahap 6
- Profil kontak menyimpan identitas dan catatan per Page. Setiap utas memiliki tag dan maksimal satu petugas aktif. Round-robin bisa diaktifkan untuk editor dan manager workspace. Jika nonaktif atau belum ada anggota yang memenuhi syarat, percakapan menunggu penugasan. Owner atau manager bisa menetapkan petugas secara manual. Editor bisa menangani utas yang belum ditugaskan atau miliknya.
- Transfer menyimpan riwayat, termasuk pelaku dan penerima penugasan. Penurunan peran menjadi viewer atau pencabutan keanggotaan melepaskan utasnya. Penerima mendapat notifikasi di aplikasi.
- Pengelola dapat mengisi departemen petugas, menjadwalkan jam layanan harian WIB, dan mengelola jawaban tersimpan. Jam layanan ditampilkan sebagai informasi. Laporan beban menampilkan percakapan terbuka dan selesai menurut penanggung jawab saat ini.

## Perubahan teknis dan bukti
service_desk.py dan templates/desk.html ditambahkan. app.py mendaftarkan modul dan migrasi versi 2 per workspace. workspace_views.py mengintegrasikan sinkronisasi Messenger, komentar, dan perubahan peran. templates/workspace.html, templates/studio.html dan static/studio.css menghubungkan tampilan. tests/test_workspaces.py menambah dua skenario integrasi.
Migrasi membuat desk_policy, desk_agents, desk_contacts, desk_pages, desk_threads, desk_messages, desk_events, desk_replies dan kolom activity.followup. Route baru meliputi GET /layanan, POST /layanan/<id>, /layanan/<id>/riwayat, /layanan/pengaturan, /layanan/notifikasi dan /komentar/<akun>/status.
33 tes lulus pada PostgreSQL 16.2. Tes baru mencakup penugasan bergilir, transfer, pesan masuk setelah resolusi, sinkronisasi ganda, pengiriman ulang form balasan, isolasi workspace, hak viewer, pagination serta lampiran. Migrasi tiga workspace dari commit 7baa884 mempertahankan draf, pesan aktivitas dan dekripsi kredensial. GET /login melalui Gunicorn lulus. Lihat HASIL-UJI-LAYANAN.txt.
Provider memakai respons simulasi selama pengujian. Izin Meta dan balasan Messenger pada akun nyata membutuhkan verifikasi setelah deploy. Inbox DM pada rilis ini khusus Facebook Messenger. Belum ada webhook pesan masuk, unggahan lampiran balasan, atau pengujian browser lintas perangkat untuk halaman baru.

## Deploy dan uji manual
1. Cadangkan database seperti di README. Gunakan project Coolify, volume dan APP_KEY yang sama. Masukkan isi folder taysriul ke root repository dan deploy satu commit.
2. Login lalu buka Interaksi > Inbox & layanan. Buka Sinkronkan akun Messenger dan pilih Page uji. Periksa nama pelanggan, akun penerima, pesan dan lampiran. Untuk balasan, konfigurasi FACEBOOK_MESSENGER_ENABLED=1 dan akun dengan izin Messenger yang disetujui provider.
3. Pada Pengaturan layanan, aktifkan routing setelah workspace mempunyai dua editor/manager. Sinkronkan dua percakapan baru, periksa pemiliknya, lalu alihkan satu. Buka riwayat penanganan dan notifikasi penerima.
4. Tandai percakapan selesai, kirim pesan baru dari akun pelanggan uji, lalu sinkronkan kembali. Periksa bahwa utas terbuka dan riwayat lama tetap ada. Balas sekali dari Taysriul dan periksa pesan di akun pelanggan.
