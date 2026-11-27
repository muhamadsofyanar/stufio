const byId = id => document.getElementById(id);
let lastFile, photoURL;
function refreshPreview() {
  const targets = Array.from(document.querySelectorAll('[name=channel]:checked'));
  const file = byId('photo').files[0];
  if (file !== lastFile) {
    if (photoURL) URL.revokeObjectURL(photoURL);
    photoURL = file ? URL.createObjectURL(file) : '';
    lastFile = file;
  }
  const src = photoURL || (byId('asset').value && '/media/'+byId('asset').value);
  const pic = byId('pic');
  pic.hidden = !src;
  if (src && pic.getAttribute('src') !== src) pic.src = src;
  byId('title').textContent = targets.map(el=>el.dataset.title+' · '+el.dataset.platform).join(', ') || 'Pilih akun tujuan';
  const text = byId('body').value;
  byId('copy').textContent = text || (src ? '' : 'Pesan Anda akan tampil di sini.');
  const length = Array.from(text.trim()).length;
  const limit = Math.min(4096,...targets.map(el=>el.dataset.platform==='Discord'?2000:(src?1024:4096)));
  byId('counter').textContent = length+' / '+limit+' karakter · '+targets.length+' tujuan';
  byId('send').disabled = !targets.length || length>limit || (!length && !src);
  byId('send').textContent = byId('due').value ? 'Jadwalkan' : 'Kirim sekarang';
}
document.getElementById('compose').addEventListener('input',refreshPreview);
document.querySelectorAll('[data-view]').forEach(tab=>tab.onclick=()=>{
  document.querySelector('.split').dataset.pane=tab.dataset.view;
  document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-pressed',String(b===tab)));
});
refreshPreview();
