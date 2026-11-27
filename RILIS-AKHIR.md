# Rilis akhir roadmap Taysriul · Tahap 7 dan 8
Paket kumulatif Tahap 1–8. Basis sumber GitHub c177d712ea2314dbe882c123d47e28727e96fd11. Tidak memuat kredensial atau data produksi.

## Deploy satu kali
Cadangkan PostgreSQL dan uji pemulihan sesuai README. Pertahankan volume, project Coolify, APP_KEY dan kredensial lama. Unggah isi folder taysriul ke root repository, lalu deploy web dan worker dari commit yang sama. Cek login dan indikator penjadwal. Migrasi versi 3 menambah tabel flow_rules, flow_runs, flow_config, flow_knowledge, flow_receipts dan kolom desk_threads.human_control pada setiap workspace. Workspace baru menerima ketiga versi skema. Tidak ada aturan bawaan yang aktif.

## Tahap 7 · Otomasi & AI
1. Sebagai owner/manager, buka Interaksi > Otomasi & AI. Buat aturan, pilih pemicu, akun opsional, kata kunci dan isi balasan. Aktifkan lalu jalankan simulasi. Pencocokan berupa potongan teks tanpa membedakan huruf besar/kecil. Aturan aktif pertama menurut ID menang. Simulasi tidak memanggil provider.
2. Pesan Messenger baru dari sinkronisasi menjalankan aksi balas. Komentar Instagram baru dari sinkronisasi atau integrasi bertanda tangan menjalankan aksi DM privat. Sinkronisasi bawaan masih manual. Pesan/komentar perlu waktu provider yang valid setelah aktivasi. Batas usia penerimaan 23 jam; antrean lebih dari satu jam dilewati. Pembacaan halaman riwayat lama tidak memicu balasan.
3. Worker mencatat reservasi per akun, kejadian dan aksi sebelum menghubungi provider. Periksa riwayat untuk hasil Terkirim, Dilewati atau Periksa platform. Status terakhir juga digunakan bila worker terhenti setelah mulai mengirim. Tidak ada pengiriman ulang otomatis untuk hasil ambigu.
4. Di Inbox, gunakan Ambil alih percakapan untuk menghentikan balasan pada utas terkait. Balasan manual juga menandai pengambilalihan. Gunakan Lanjutkan otomasi untuk mengembalikan kontrol. Kebijakan jeda aktif sejak awal. DM privat Instagram tampil pada inbox bila provider mengembalikan ID penerima dan pesan. Riwayat DM masuk Instagram penuh belum tersinkron; inbox dua arah pada rilis ini menggunakan Messenger.
5. Tambahkan dokumen di Pengetahuan workspace. Di utas Messenger, pilih Susun draf. Atas tindakan operator, aplikasi mengirim teks pesan terakhir dan hingga empat sumber workspace ke OpenAI. Model memilih kutipan; backend memeriksa kutipan terhadap sumber asli sebelum menampilkan draf. Petugas meninjau, mengedit dan menekan Kirim. Jika sumber tidak memuat jawaban yang bisa diverifikasi, draf tidak dibuat.

| Variabel Coolify | Kegunaan |
|---|---|
| FACEBOOK_MESSENGER_ENABLED=1 | Mengizinkan balasan Messenger jika token dan izin Meta memenuhi syarat |
| INSTAGRAM_PRIVATE_REPLIES_ENABLED=1 | Mengizinkan aksi balas komentar via DM privat bila diizinkan Meta |
| TAYSRIUL_AI_KEY | Kunci OpenAI untuk permintaan draf oleh operator |
| TAYSRIUL_AI_MODEL | ID model pada akun yang mendukung Chat Completions dengan pesan system/user |

## Integrasi server ke server
Buat kunci khusus workspace pada halaman Otomasi. Kunci ditampilkan sekali. Rotasi membatalkan kunci lama. Ini endpoint integrasi Taysriul, bukan endpoint verifikasi langganan webhook Meta. Kirim JSON UTF-8 melalui HTTPS menggunakan POST. Hitung HMAC-SHA256 atas byte timestamp Unix desimal, titik, path absolut, titik, lalu byte body persis seperti dikirim. Header X-Taysriul-Time memuat timestamp; X-Taysriul-Signature memuat heksadesimal HMAC. Toleransi waktu lima menit. Gunakan ID akun OAuth lokal dari workspace yang memiliki kunci.

| Path | Bidang JSON |
|---|---|
| /integrasi/WID/komentar | account (integer), comment_id, sender_id, text, created_time (ISO dengan offset zona waktu). Kirim komentar Instagram yang benar-benar diterima dari provider. Pengulangan ID komentar tidak menambah eksekusi. |
| /integrasi/WID/metrik | account (integer), date (YYYY-MM-DD), metric (reach, impressions atau engagement), value (integer nonnegatif). Kirim pengukuran harian provider; pengiriman ulang memperbarui nilai pada akun dan hari yang sama. |

Contoh pembuatan header pada layanan pengirim:
```python
import hashlib, hmac, json, time
raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
ts = str(int(time.time()))
signature = hmac.new(secret.encode(), ts.encode() + b"." + path.encode() + b"." + raw, hashlib.sha256).hexdigest()
headers = {"Content-Type":"application/json","X-Taysriul-Time":ts,"X-Taysriul-Signature":signature}
# Kirim raw sebagai body ke origin Taysriul + path; jangan serialisasi ulang.
```

## Tahap 8 · Laporan kinerja
Pilih tanggal mulai dan akhir dalam WIB. Publikasi menampilkan jumlah per tujuan terjadwal dalam periode, status terkini, caption, ID materi dan akun. Satu konten yang dikirim ke tiga akun dihitung sebagai tiga kiriman tujuan. Reach, impressions dan engagement disajikan per akun/hari jika datanya tersedia melalui integrasi. Snapshot lain memakai data provider yang sudah tersimpan di metric_days. Tidak ada estimasi reach atau engagement per konten.
Laporan CS memilih percakapan berdasarkan waktu pesan masuk pertama yang tersedia. Beban kerja dikelompokkan menurut pemilik saat ini. Respons pertama memakai selisih antara pesan masuk pertama dan balasan terkonfirmasi pertama, termasuk otomasi. Rerata resolusi menghitung percakapan yang masih berstatus selesai. Tindakan petugas dihitung terpisah menurut waktu kejadian dan pelaku. Empat ekspor CSV mengikuti periode layar. Nilai kosong dan angka nol ditampilkan berbeda.

## Bukti dan batas pengujian
35 tes lulus di PostgreSQL 16.2. Skenario baru menguji aturan dan simulasi, deduplikasi, jeda setelah handover, draf AI berbasis kutipan, penolakan kutipan yang tidak ada, tanda tangan webhook, DM privat dan pencatatan inbox, serta nilai reach nol dari integrasi. Laporan layanan dan CSV diuji dari data pesan lokal. Migrasi dari commit c177d71 pada tiga workspace mempertahankan draf, pesan dan dekripsi token. Gunicorn melayani /login. Hasil tes disertakan dalam HASIL-UJI-AKHIR.txt.
Pengujian panggilan Meta dan OpenAI memakai respons simulasi. Izin private replies, akses model, tagihan aktual, serta tampilan lintas perangkat perlu diuji pada instalasi tujuan. Untuk penerimaan, gunakan satu akun dan satu aturan uji sebelum memperluas cakupan.

## Daftar perubahan
Modul baru workflows.py dan reports.py; tampilan baru templates/workflows.html dan templates/reports.html. Perubahan pada app.py, service_desk.py, workspace_views.py, meta_activity.py, docker-compose.yaml, templates/studio.html, templates/desk.html, tests/test_workspaces.py dan README.md. Route aplikasi baru meliputi /otomasi, /laporan, /layanan/<id>/asisten serta kedua endpoint integrasi di atas.
