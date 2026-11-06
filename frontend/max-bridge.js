/* MAX owns the launch fragment; the school router starts after Bridge reads it. */
(() => {
  const root = document.documentElement;
  const media = window.matchMedia('(prefers-color-scheme: dark)');
  let preference = 'system';
  try { preference = localStorage.getItem('maks-appearance') || 'system'; } catch (_) {}
  if (!['system', 'light', 'dark'].includes(preference)) preference = 'system';
  function applyAppearance() {
    root.dataset.theme = preference === 'system' ? (media.matches ? 'dark' : 'light') : preference;
  }
  applyAppearance();
  if (media.addEventListener) media.addEventListener('change', applyAppearance);
  else if (media.addListener) media.addListener(applyAppearance);
  window.bindAppearance = () => {
    if (location.hash.split('?')[0] !== '#profile') return;
    const params = new URLSearchParams(location.hash.split('?')[1] || '');
    if (params.has('id')) return;
    const card = document.createElement('section');
    card.className = 'card appearance-card';
    card.innerHTML = '<h2>Оформление</h2><label>Тема приложения<select aria-label="Тема приложения"><option value="system">Как на устройстве</option><option value="light">Светлая</option><option value="dark">Тёмная</option></select></label>';
    const select = card.querySelector('select');
    select.value = preference;
    select.onchange = () => {
      preference = select.value;
      try { localStorage.setItem('maks-appearance', preference); } catch (_) {}
      applyAppearance();
    };
    document.getElementById('app').appendChild(card);
  };

  const appSource = document.currentScript.dataset.app;
  const launch = new URLSearchParams(location.hash.slice(1));
  const fromMax = launch.has('WebAppData');
  const signedLaunch = launch.get('WebAppData') || '';
  window.maksMaxInitData = () => signedLaunch || window.WebApp?.initData || '';
  let started = false;

  function start() {
    if (started) return;
    started = true;
    if (fromMax) history.replaceState(null, '', location.pathname + location.search + '#home');
    const app = document.createElement('script');
    app.src = appSource;
    app.onload = connectBackButton;
    document.body.appendChild(app);
  }

  function connectBackButton() {
    const back = fromMax && window.WebApp && window.WebApp.BackButton;
    if (!back) return;
    const sync = () => {
      const visible = document.querySelector('dialog[open]') ||
        !['', '#home', '#login'].includes(location.hash);
      try { visible ? back.show() : back.hide(); } catch (_) { /* Browser fallback. */ }
    };
    back.onClick(() => {
      const dialog = document.querySelector('dialog[open]');
      if (dialog) dialog.close();
      else location.hash = '#home';
      sync();
    });
    window.addEventListener('hashchange', sync);
    new MutationObserver(sync).observe(document.getElementById('modal'), {
      attributes: true, attributeFilter: ['open'],
    });
    sync();
  }

  if (!fromMax) return start();
  // Launch data is never used to grant a school role or replace the access code.
  const bridge = document.createElement('script');
  bridge.src = 'https://st.max.ru/js/max-web-app.js';
  const timeout = setTimeout(start, 5000);
  bridge.onload = bridge.onerror = () => { clearTimeout(timeout); start(); };
  document.head.appendChild(bridge);
})();
