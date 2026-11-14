// The type card loads one still. Only an explicit activation creates a Designer frame.
(() => {
  'use strict';
  const card = document.getElementById('fc3d');
  if (!card) return;
  const select = card.querySelector('select');
  const preview = card.querySelector('.fc3d-preview');
  const stage = preview.querySelector('.fc3d-stage');
  const image = stage.querySelector('img');
  const caption = preview.querySelector('figcaption');
  const toggle = preview.querySelector('button');
  const status = preview.querySelector('[role="status"]');
  let frame = null;
  let timer;

  function close() {
    clearTimeout(timer);
    if (frame) frame.remove();
    frame = null;
    preview.classList.remove('is-live');
    toggle.textContent = preview.dataset.rotate;
    toggle.setAttribute('aria-expanded', 'false');
    status.textContent = '';
  }
  function update() {
    close();
    const choice = select.selectedOptions[0];
    image.src = choice.dataset.poster;
    caption.textContent = choice.dataset.caption;
  }
  toggle.addEventListener('click', () => {
    if (frame) { close(); return; }
    const choice = select.selectedOptions[0];
    frame = document.createElement('iframe');
    frame.title = caption.textContent + ' · 3D';
    frame.tabIndex = -1;
    frame.referrerPolicy = 'strict-origin-when-cross-origin';
    frame.src = choice.dataset.view;
    toggle.textContent = preview.dataset.close;
    status.textContent = preview.dataset.loading;
    stage.append(frame);
    timer = setTimeout(() => {
      close();
      status.textContent = preview.dataset.failed;
    }, 20000);
  });
  window.addEventListener('message', (event) => {
    if (!frame || event.source !== frame.contentWindow) return;
    const url = new URL(frame.src);
    if (event.origin !== url.origin || !event.data) return;
    if (event.data.type === 'aircraft-preview-close') {
      close();
      toggle.focus({ preventScroll:true });
    } else if (event.data.type === 'aircraft-preview-ready' &&
        event.data.aircraft === url.searchParams.get('aircraft') && event.data.layout === url.searchParams.get('layout')) {
      clearTimeout(timer);
      preview.classList.add('is-live');
      toggle.textContent = preview.dataset.close;
      toggle.setAttribute('aria-expanded', 'true');
      status.textContent = '';
      frame.tabIndex = 0;
      frame.contentWindow.focus();
    }
  });
  select.addEventListener('change', update);
  window.addEventListener('pageshow', update);
  update();
  toggle.hidden = false;
})();
