# Acuan UI/UX Studio Taysriul

Dokumen ini mendampingi ROADMAP.md. Pola berikut adalah target rancangan. Kanal dengan alur yang tersedia saat ini adalah Telegram dan Discord. Tampilkan tindakan untuk kanal lain ketika integrasinya siap.

## Navigasi dan bahasa visual

Gunakan sidebar lavender dengan identitas workspace di atas, tombol Buat post tepat di bawahnya, serta penanda menu aktif yang tetap terbaca tanpa mengandalkan warna. Kelompok Publikasi berisi Postingan, Ide, Media dan Tautan. Kelompok Interaksi mencakup Komentar, Inbox, Feed, Otomasi dan Agen. Analitik berisi Statistik. Akun menyediakan pintu masuk untuk menghubungkan kanal. Gunakan nama fitur dalam bahasa Indonesia secara konsisten.

Area kerja memakai latar terang, kartu putih, garis pembatas tipis dan satu tombol utama ungu per tugas. Jumlah pada menu berasal dari data workspace. Di HP gunakan navigasi ringkas, editor dan pratinjau bergantian, serta tombol yang mudah dijangkau.

## Alur layar

| Layar | Pola yang diambil | Kriteria rancangan |
|---|---|---|
| Hubungkan akun | Pilihan platform berbentuk kartu dengan ikon, nama dan jenis akun. | Rencanakan Instagram, Threads, Facebook Page, TikTok, LinkedIn, YouTube, X, Telegram, Discord dan Pinterest. Tampilkan status ketersediaan dan alasan jika aksi belum tersedia. |
| Koneksi Telegram | Instruksi bertahap di satu dialog. | Perlihatkan identitas bot milik pengguna, channel tujuan, izin mengirim dan hasil verifikasi. Saat gagal, pengguna tahu langkah yang perlu diulang. |
| Buat post | Akun tujuan di atas, editor di kiri, pratinjau di kanan, aksi terbit di bawah. | Untuk multiakun, tulis caption umum lalu sesuaikan per akun. Tunjukkan media yang masih dibutuhkan serta tujuan dan waktu WIB sebelum kirim. |
| Papan ide | Kolom Ide, Dikerjakan dan Siap, dengan aksi tambah per kolom. | Kartu yang siap dapat dibuka sebagai draf dengan isi yang sudah ditulis. |
| Media | Filter Semua, Foto dan Video, tombol Unggah, indikator penyimpanan. | Pilih aset untuk digunakan kembali di editor. Tampilkan penggunaan aktual dan jelaskan kebijakan retensi hanya bila diterapkan. |
| Tautan | Dialog ringkas berisi URL tujuan, nama tautan dan judul opsional. | Tampilkan domain milik pengguna dan contoh URL akhir. Beri kesalahan di kolom nama bila sudah dipakai. |
| Komentar dan Inbox | Percakapan disertai konteks postingan asal, akun dan waktu. | Filter Perlu dibalas, Selesai dan Semua. Aksi balas tersedia sesuai izin akun. |
| Otomasi | Saat kosong, jelaskan akun yang dibutuhkan dan sediakan aksi hubungkan. | Saat akun siap, pengguna dapat menentukan pemicu, tindakan dan tujuan sebelum mengaktifkan aturan. |
| Agen AI | Pengaturan kunci API, instruksi dan basis pengetahuan dalam workspace. | Pengelola dapat menguji satu draf balasan sebelum memakai agen pada percakapan. |

## Konteks instalasi mandiri

Tangkapan panel VPS memberi konteks kapasitas server bersama. Ukuran media dan pekerjaan latar perlu dipertimbangkan dalam desain. Gunakan identitas Studio Taysriul, domain dan bot sendiri. Batas akun, harga per posting, kuota media dan batas jumlah agen mengikuti konfigurasi nyata jika kelak diberlakukan.

## Prioritas desain berikutnya

Mulai dengan alur Ide → Draf → Pilih media → Pratinjau → Jadwalkan. Uji dengan satu pengumuman yang memakai foto dari pustaka. Pengguna harus bisa melihat channel dan waktu WIB, kembali mengedit tanpa kehilangan isi, lalu menemukan kirimannya di kalender.
