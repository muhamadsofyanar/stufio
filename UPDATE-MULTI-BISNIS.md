# Taysriul untuk multi-bisnis internal

Paket ini melanjutkan rilis Tahap 1–8 dari main 5.zip. Buat satu workspace untuk setiap bisnis melalui **Tim & pengaturan**. Gunakan peran pengelola, editor, atau pembaca untuk membatasi akses tim. Nilai `WID` adalah ID numerik workspace yang sudah ada.

## Pasang pada staging

Ikuti pencadangan dan pemulihan di README. Pertahankan `APP_KEY`, database dan volume pada instalasi yang diperbarui. Gunakan kode yang sama untuk web dan worker. Paket ini memakai tabel dan kolom yang sudah ada di rilis Tahap 1–8. Integrasi opsional dipasang melalui variabel lingkungan privat di Compose atau Coolify. Jika kosong atau workspace tidak tercantum, fitur publikasi langsung yang sudah ada tetap digunakan.

## Tebar

Siapkan token baca dan tulis untuk bisnis yang terhubung. Dapatkan ID akun tujuan dari `GET /v1/accounts`. Petakan identitas akun lokal dari halaman **Akun sosial** ke ID Tebar. Contoh di bawah menggunakan ID dan token contoh.

```dotenv
TAYSRIUL_TEBAR='{"1":{"token":"TOKEN_BISNIS_1","accounts":{"instagram:ID_AKUN_PLATFORM":"ID_AKUN_TEBAR"}},"2":{"token":"TOKEN_BISNIS_2","accounts":{"threads:ID_AKUN_PLATFORM":"ID_AKUN_TEBAR"}}}'
SOCIAL_ORIGIN=https://taysriul.example.com
```

Akun lokal harus aktif dan siap publikasi. Pilot mendukung Facebook, Instagram, Threads, LinkedIn profil, dan X. Gunakan token masing-masing bisnis. Periksa nilai platform dan ID agar cocok dengan identitas akun di kedua layanan. Tetapkan pemetaan sebelum membuat jadwal baru. Kiriman lama tetap menggunakan jalur yang ditetapkan saat dibuat. Ketika worker mencapai jadwal, Tebar menerima satu kiriman per tujuan. Foto dan video memakai URL media HTTPS bertanda tangan.

Status `Diproses platform` berarti Tebar sudah menerima pekerjaan. Worker memeriksa hasil per akun setelah sekitar 45 detik. Status `Terbit` mengikuti konfirmasi Tebar. Periksa dashboard Tebar sebelum mengulang kiriman berstatus `Periksa channel`. Tebar menagih atau membatasi pemakaian sesuai paket akun yang digunakan.

## BalasChat

Pilot menerima pesan masuk dan mengirim balasan teks dari satu nomor WhatsApp Business resmi per workspace. Gunakan slug subdomain BalasChat sebagai `workspace` dan nomor identitas WABA sebagai `phone_number_id`.

```dotenv
TAYSRIUL_BALASCHAT='{"1":{"workspace":"bisnis-a","phone_number_id":"123456789","secret":"SIGNING_SECRET_A","token":"API_TOKEN_A"},"2":{"workspace":"bisnis-b","phone_number_id":"987654321","secret":"SIGNING_SECRET_B","token":"API_TOKEN_B"}}'
```

Tambahkan webhook di BalasChat dengan URL `https://DOMAIN_TAYSRiUL/integrasi/WID/balaschat`. Setelah memperoleh signing secret, isi konfigurasi lalu redeploy. Gunakan signing secret yang berbeda untuk setiap bisnis. Aktifkan event pesan masuk lalu jalankan **Send test**. Webhook memeriksa tanda tangan dan mencocokkan workspace serta nomor WABA sebelum menyimpan pesan. Pesan muncul di **Inbox & layanan** dan dapat ditugaskan, diberi tag, atau ditutup. Balasan teks tersedia selama 24 jam sejak pesan terakhir pelanggan. Status awal mengikuti penerimaan API. Status baca, sinkronisasi pesan yang dikirim di dashboard BalasChat, dan pesan template di luar jendela 24 jam berada di luar cakupan rilis ini.

## StarSender untuk WhatsApp

Hubungkan perangkat di dashboard StarSender, lalu ambil Device API Key dan ID perangkat. Atur satu perangkat StarSender per workspace Taysriul. Gunakan perangkat atau nomor berbeda jika Anda juga mengaktifkan BalasChat pada bisnis yang sama.

```dotenv
TAYSRIUL_STARSENDER='{"1":{"device_id":"ID_DEVICE","token":"DEVICE_API_KEY","secret":"GANTI_DENGAN_TOKEN_ACAK_MINIMAL_32_KARAKTER"}}'
```

Buat secret dengan `python -c "import secrets; print(secrets.token_urlsafe(32))"`. Atur URL webhook pesan masuk pada perangkat StarSender menjadi `https://DOMAIN/integrasi/WID/starsender/SECRET`. Ganti WID dengan ID workspace Taysriul dan SECRET dengan nilai di konfigurasi. Batasi akses ke URL ini dan sensor nilainya di log reverse proxy. Webhook standar yang terdokumentasi memuat pengirim, teks, dan timestamp. Taysriul memvalidasi secret unik per workspace, serta mencocokkan ID perangkat jika payload menyertakannya.

Kirim pesan teks pribadi ke nomor tersebut. Percakapan muncul di **Inbox & layanan** sebagai **WhatsApp · StarSender**. Balas dari inbox dan cek status **Diterima API**. Status ini menunjukkan API menerima permintaan. Pengujian penerimaan di ponsel tetap diperlukan karena dokumentasi API tidak menyertakan konfirmasi sampai atau dibaca dalam respons kirim. Paket ini mencakup chat pribadi dan balasan teks. Jika webhook membawa ID pesan, Taysriul memakai ID tersebut untuk deduplikasi. Untuk webhook dasar, deduplikasi memakai pengirim, timestamp dan teks.

## Penjadwalan massal

Di **Buat post**, centang setiap akun yang boleh dipakai di batch. Unggah CSV UTF-8 maksimal 100 materi. Kolom `targets` opsional. Pakai ID yang tampil di editor, pisahkan dengan spasi. Nilai kosong memakai semua akun yang dicentang. Waktu mengikuti WIB. Kolom `asset` memakai ID media dari workspace yang sedang aktif. Sistem mengikuti aturan persetujuan workspace dan membatalkan seluruh batch jika ada baris yang gagal validasi.

```csv
caption,due,asset,targets
Promo cabang,2027-01-15T09:00,12,oauth:4 oauth:7
Informasi jam buka,2027-01-16T10:00,,oauth:7
```

## Rencana 5 langkah

1. Jalankan suite PostgreSQL di staging dan uji migrasi dari salinan database aktif.
2. Hubungkan satu akun Tebar dan satu perangkat StarSender atau satu nomor WABA untuk satu bisnis. Uji satu kiriman, satu pesan masuk, dan satu balasan.
3. Masukkan bisnis lain bertahap. Uji pergantian workspace, izin tim, dan batch CSV dengan akun tujuan berbeda.
4. Tambahkan tautan unik per kampanye serta tag prospek di inbox untuk mengukur percakapan yang bisa dikaitkan ke promosi.
5. Buat ringkasan pemilik lintas bisnis untuk hasil publikasi, jumlah chat terbuka, waktu respons pertama, dan prospek. Tinjau hasilnya setiap bulan.

## Referensi

- [Manypage](https://pt-booster-teknologi-indonesias.gitbook.io/manypage.id)
- [Tebar API Post](https://docs.tebar.app/api/posts/)
- [BalasChat webhook](https://doc.balaschat.my.id/docs/webhook-balaschat/)
- [BalasChat WABA](https://doc.balaschat.my.id/docs/api-whatsapp-business-waba/)
- [StarSender API kirim pesan](https://docs.starsender.online/docs/message-api/kirim-pesan/)
- [StarSender webhook](https://docs.starsender.online/docs/webhook/)
