document.addEventListener('click', event => {
  const opener=event.target.closest('[data-open]');
  if(opener) document.getElementById(opener.dataset.open).showModal();
  const closer=event.target.closest('[data-close]');
  if(closer) closer.closest('dialog').close();
});
