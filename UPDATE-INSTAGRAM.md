# Instagram Unified Login — hotfix
Untuk instalasi Stufio MultiPlatform sebelumnya. Ganti hanya social_oauth.py dan docker-compose.yaml di root GitHub. File test bersifat opsional.
ENV Coolify:
INSTAGRAM_LOGIN_MODE=unified
INSTAGRAM_CONFIG_ID=29306720278980796
INSTAGRAM_CLIENT_ID=1561021147091834
INSTAGRAM_CLIENT_SECRET=App Secret stufio2 (jangan commit nilai sebenarnya)
Callback: https://taysriulqurani.id/akun/oauth/instagram/callback
Pertahankan seluruh ENV dan volume yang lama. Redeploy lalu klik Hubungkan Instagram. Pilih aset yang Anda kelola. Uji posting foto JPEG terlebih dahulu.
Unified mode memakai config_id, state OAuth, token hasil pertukaran code tanpa pertukaran token Facebook jangka panjang, debug_token untuk verifikasi app/izin, dan aset Instagram yang diberikan oleh Meta.
Uji simulasi lokal: 17 test lulus. Belum ada uji live Meta atau Docker/PostgreSQL nyata. Jika Meta menolak token atau daftar aset kosong, kirim pesan error tanpa token/secret; jangan mengulang konfigurasi Facebook.
