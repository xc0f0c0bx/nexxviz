/* nexxxen visualizer drop-in: adds a shader selector card to Settings -> Display. */
(() => {
  if (window.__nexxvisEmbed) return;
  window.__nexxvisEmbed = true;
  const API = '/visualizer/api';
  const PATH = '/services/display';

  async function getState() {
    const r = await fetch(API + '/state', { cache: 'no-store' });
    if (!r.ok) throw new Error('selector unavailable');
    return r.json();
  }

  function makeCard() {
    const card = document.createElement('section');
    card.className = 'nexxvis-card';
    card.setAttribute('data-nexxvis', '1');
    card.style.cssText = [
      'margin:1.5rem 0', 'padding:1.1rem 1.25rem', 'border-radius:14px',
      'border:1px solid rgba(127,127,127,.3)', 'background:rgba(127,127,127,.07)'
    ].join(';');
    card.innerHTML =
      '<h2 style="margin:0 0 .2rem;font-size:1.1rem">Visualizer</h2>' +
      '<p style="margin:0 0 .9rem;opacity:.72;font-size:.9rem">' +
      'Shader shown on the TV. Auto resumes the 5-minute cycle.</p>' +
      '<div style="display:flex;gap:.6rem;align-items:center;flex-wrap:wrap">' +
      '<select class="nv-sel" aria-label="Visualizer shader" ' +
      'style="flex:1;min-width:12rem;padding:.6rem;border-radius:9px;' +
      'border:1px solid rgba(127,127,127,.35);background:transparent;color:inherit"></select>' +
      '<button class="nv-apply" style="padding:.6rem 1.1rem;border:0;border-radius:9px;' +
      'background:#38bdf8;color:#06121c;font-weight:700">Apply</button>' +
      '<button class="nv-like" style="padding:.6rem .9rem;border:0;border-radius:9px;' +
      'background:#34d399;color:#062016;font-weight:700">Like</button>' +
      '<button class="nv-dislike" style="padding:.6rem .9rem;border:0;border-radius:9px;' +
      'background:#f87171;color:#2a0606;font-weight:700">Dislike</button>' +
      '<a href="/visualizer/" style="font-size:.85rem">Open full page</a></div>' +
      '<p class="nv-msg" style="margin:.6rem 0 0;font-size:.85rem;opacity:.75"></p>';
    const sel = card.querySelector('.nv-sel');
    const msg = card.querySelector('.nv-msg');
    const btn = card.querySelector('.nv-apply');
    getState().then(s => {
      sel.innerHTML = '';
      for (const o of [{ file: 'auto', name: 'Auto cycle' }, ...s.shaders]) {
        const opt = document.createElement('option');
        opt.value = o.file; opt.textContent = o.name;
        sel.appendChild(opt);
      }
      sel.value = s.current;
    }).catch(err => { msg.textContent = err.message; });
    btn.addEventListener('click', async () => {
      btn.disabled = true; msg.textContent = 'Applying…';
      try {
        const r = await fetch(API + '/select', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ shader: sel.value }),
        });
        const s = await r.json();
        if (!r.ok) throw new Error(s.error || 'failed');
        msg.textContent = 'Active: ' + (s.current === 'auto' ? 'Auto cycle' : s.current);
      } catch (err) { msg.textContent = 'Error: ' + err.message; }
      btn.disabled = false;
    });
    async function feedback(reward) {
      try {
        const r = await fetch(API + '/feedback', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ reward: reward }),
        });
        const s = await r.json();
        if (!r.ok) throw new Error(s.error || 'failed');
        msg.textContent = (reward > 0 ? 'Noted: like' : 'Noted: dislike') +
          ' · ' + s.n + ' samples';
      } catch (err) { msg.textContent = 'Error: ' + err.message; }
    }
    card.querySelector('.nv-like').addEventListener('click', () => feedback(1));
    card.querySelector('.nv-dislike').addEventListener('click', () => feedback(-1));
    return card;
  }

  function inject() {
    if (location.pathname !== PATH) return;
    const main = document.querySelector('main');
    if (!main || main.querySelector('[data-nexxvis]')) return;
    main.appendChild(makeCard());
  }

  new MutationObserver(inject).observe(document.documentElement,
    { childList: true, subtree: true });
  window.addEventListener('popstate', inject);
  const push = history.pushState;
  history.pushState = function () { push.apply(this, arguments); setTimeout(inject, 60); };
  setInterval(inject, 1000);
  inject();
})();
