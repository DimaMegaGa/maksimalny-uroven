function maxNotificationContext() {
  return {maxInitData: window.maksMaxInitData?.() || window.WebApp?.initData || ''};
}

const maxPendingConnections = new Map();

function bindMaxNotifications() {
  const viewer = currentUser();
  const requested = new URLSearchParams(location.hash.split('?')[1] || '').get('id');
  if (page() !== 'profile' || !['student', 'teacher'].includes(viewer?.role) ||
      (requested && requested !== viewer.id)) return;
  const card = document.createElement('section');
  card.className = 'card';
  card.style.marginTop = '24px';
  card.id = 'max-notifications';
  card.innerHTML = '<h2>Уведомления MAX</h2><p role="status">Проверяем подключение…</p>';
  app.appendChild(card);
  const same = () => card.isConnected && currentUser()?.id === viewer.id;
  const error = (value) => {
    if (same()) card.querySelector('[role="status"]').textContent = value.message;
  };
  function showPending(result) {
    card.innerHTML = `<h2>Подключение уведомлений MAX</h2><p class="subtitle">Открой бота по кнопке и нажми «Начать», если MAX предложит. Ссылка одноразовая и действует 5 минут — не передавай её другим.</p><p><a class="btn" href="${esc(result.url)}" target="_blank" rel="noreferrer noopener">Открыть бота MAX</a></p><p>Если подключение не появилось, отправь боту эту команду:</p><p style="overflow-wrap:anywhere"><code>${esc(result.command)}</code></p><p role="status">После подтверждения в боте вернись сюда.</p><button class="btn outline" data-max-refresh>Проверить подключение</button>`;
  }
  async function refresh() {
    try {
      const status = await api('max/settings', maxNotificationContext());
      if (!same()) return;
      const pending = maxPendingConnections.get(viewer.id);
      if (status.connected || (pending && pending.expiresAt <= Date.now())) maxPendingConnections.delete(viewer.id);
      else if (status.available && pending) return showPending(pending);
      card.innerHTML = `<h2>Уведомления MAX</h2><p class="subtitle">Новые задания, проверка работ и решения по обмену баллов — сообщениями от бота. Коды входа не отправляются.</p><p role="status">${status.connected ? 'Подключены. Обычно сообщение приходит в течение минуты. Звук и показ на телефоне зависят от настроек MAX.' : status.differentAccount ? 'Эта школьная учётка связана с другим аккаунтом MAX. Нажмите «Подключить MAX» и подтвердите замену в боте. Уведомления будут приходить только на подтверждённый аккаунт.' : status.available ? 'Уведомления пока не подключены.' : 'Уведомления MAX пока недоступны на этом сервере.'}</p><div class="subject-tags">${status.connected ? '<button class="btn soft" data-max-test>Проверить доставку</button><button class="btn outline" data-max-disconnect>Отключить</button>' : status.available ? '<button class="btn" data-max-connect>Подключить MAX</button>' : ''}<button class="btn outline" data-max-refresh>Проверить подключение</button></div>${status.failed ? '<p class="form-error">Есть недоставленные сообщения. Проверьте, что бот не заблокирован.</p>' : ''}`;
    } catch (value) { error(value); }
  }
  card.onclick = async (event) => {
    const button = event.target.closest('button');
    if (!button || button.disabled) return;
    button.disabled = true;
    try {
      if (button.hasAttribute('data-max-connect')) {
        const result = await api('max/connect', maxNotificationContext());
        if (!same()) return;
        maxPendingConnections.set(viewer.id, {...result, expiresAt: Date.now() + result.expiresIn * 1000});
        showPending(result);
      } else if (button.hasAttribute('data-max-disconnect')) {
        await api('max/disconnect', maxNotificationContext());
        await refresh();
      } else if (button.hasAttribute('data-max-test')) {
        await api('max/test', maxNotificationContext());
        if (same()) card.querySelector('[role="status"]').textContent = 'Проверочное сообщение поставлено в очередь. Обычно доставка занимает до минуты.';
      } else await refresh();
    } catch (value) { error(value); }
    finally { button.disabled = false; }
  };
  refresh();
}
