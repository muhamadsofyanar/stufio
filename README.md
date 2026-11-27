# Studio Taysriul

Dashboard admin tunggal dan scheduler Telegram mandiri. Foto dan token terenkripsi (khusus token) disimpan di PostgreSQL. Worker mengirim dari server walaupun browser ditutup. Tidak menggunakan Node.js, Redis atau sharp.

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
