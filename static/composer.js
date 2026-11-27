const byId = id => document.getElementById(id);
const capabilities = {Telegram:['text','image','video'],Discord:['text','image','video'],facebook:['text','image','video'],instagram:['image','video'],threads:['text','image','video'],youtube:['video'],tiktok:['video'],linkedin:['text','image','video'],x:['text','image','video'],pinterest:['image','video']};
const limits = {Discord:2000,instagram:2200,threads:500,linkedin:3000,x:280,pinterest:500};
let lastFile, mediaURL;
function refreshPreview() {
  const targets=Array.from(document.querySelectorAll('[name=channel]:checked'));
  const file=byId('photo').files[0];
  if(file!==lastFile){if(mediaURL) URL.revokeObjectURL(mediaURL);mediaURL=file?URL.createObjectURL(file):'';lastFile=file;}
  const asset=byId('asset'), src=mediaURL||(asset.value&&'/media/'+asset.value+'?ws='+byId('compose').dataset.workspace);
  const kind=file?((file.type==='video/mp4'||/\.mp4$/i.test(file.name))?'video':'image'):(asset.value?asset.selectedOptions[0].dataset.kind:'text');
  const text=byId('body').value.trim(), length=Array.from(text).length;
  const limit=Math.min(4096,...targets.map(el=>el.dataset.platform==='Telegram'?(kind==='text'?4096:1024):(limits[el.dataset.platform]||4096)));
  byId('cover_options').hidden=!targets.some(t=>t.dataset.platform==='pinterest');
  byId('youtube_visibility_options').hidden=!targets.some(t=>t.dataset.platform==='youtube');
  byId('youtube_kids_options').hidden=byId('youtube_visibility_options').hidden;
  function mediaFor(target) {
    const select=byId('compose').elements.namedItem('media_'+target.value);
    if (!select?.value) return {kind,src};
    if (select.value==='none') return {kind:'text',src:''};
    return {kind:select.selectedOptions[0].dataset.kind,src:'/media/'+select.value+'?ws='+byId('compose').dataset.workspace};
  }
  const issues=[];
  for(const target of targets){
    const {kind,src}=mediaFor(target);
    const key=target.dataset.platform;
    const caption=byId('compose').elements.namedItem('caption_'+target.value)?.value.trim()||text;
    const max=key==='Telegram'?(kind==='text'?4096:1024):(limits[key]||4096);
    if(Array.from(caption).length>max) issues.push(target.dataset.title+' melebihi batas caption.');
    if(!caption&&!src) issues.push('Isi caption atau media untuk '+target.dataset.title+'.');
    if(!capabilities[key]?.includes(kind))issues.push(target.dataset.title+' tidak mendukung media ini.');
    if(key==='pinterest'&&kind==='video'&&!byId('cover').value)issues.push('Pilih cover video Pinterest.');
    if(key==='youtube'&&(!caption||caption.split('\n')[0].length>100))issues.push('YouTube memerlukan judul hingga 100 karakter.');
    if(key==='youtube'&&!byId('youtube_kids').value)issues.push('Pilih audiens YouTube.');
    if(key==='instagram'&&src===mediaURL&&file&&kind==='image'&&file.type!=='image/jpeg')issues.push('Instagram memerlukan JPEG.');
  }
  if(file&&file.size>(kind==='video'?32:8)*1024*1024)issues.push('Ukuran media terlalu besar.');
  const previews=byId('previews');
  previews.replaceChildren();
  if(!targets.length) previews.textContent='Pilih akun untuk melihat pratinjau.';
  for(const target of targets){
    const {kind,src}=mediaFor(target);
    const card=document.createElement('article');
    const platform=document.createElement('small');
    platform.textContent=target.dataset.platform;
    const title=document.createElement('h2');
    title.textContent=target.dataset.title;
    card.append(platform,title);
    if(src){
      const media=document.createElement(kind==='video'?'video':'img');
      media.src=src;
      if(kind==='video'){media.controls=true;media.preload='metadata';}
      else media.alt='Pratinjau foto';
      card.append(media);
    }
    const caption=document.createElement('p');
    caption.className='body';
    caption.textContent=byId('compose').elements.namedItem('caption_'+target.value)?.value.trim()||text||'Belum ada caption.';
    card.append(caption);
    previews.append(card);
  }
  byId('counter').textContent=length+' / '+limit+' karakter · '+targets.length+' tujuan';
  byId('validation').textContent=issues.join(' ');
  byId('send').disabled=!targets.length||issues.length>0;
  byId('send').textContent=byId('compose').dataset.approval==='1'?'Ajukan untuk persetujuan':byId('due').value?'Jadwalkan':'Kirim sekarang';
}
byId('compose').addEventListener('input',refreshPreview);
document.querySelectorAll('[data-view]').forEach(tab=>tab.onclick=()=>{document.querySelector('.split').dataset.pane=tab.dataset.view;document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-pressed',String(b===tab)));});
refreshPreview();
