let directorOrganization = '',
  directorQuery = '';
function directorHome() {
  const accounts = admin?.accounts || [],
    packets = admin?.packages || [];
  return (
    heading(
      'Кабинет директора',
      'Готовые списки и персональные коды поступают из кабинета министерства.',
      '<button class="btn" data-go="directorInbox">Открыть входящие</button>'
    ) +
    `<div class="metrics">${metric(documentSymbol(), '', 'Новых пакетов', packets.filter((p) => !p.openedAt).length, 'directorInbox')}${metric('♙', '', 'Учителей', accounts.filter((a) => a.role === 'teacher').length, 'directorTeachers')}${metric('✦', 'green', 'Учеников', accounts.filter((a) => a.role === 'student').length, 'directorStudents')}</div><details class="card director-guide portal-guide"><summary>Как распределить доступ</summary><ol><li>Откройте новое сообщение во вкладке «Входящие».</li><li>Проверьте организацию и список, прочитайте приложенную инструкцию.</li><li>Передайте каждому участнику только его ФИО и персональный код.</li><li>Когда закончите, отметьте пакет как распределённый.</li></ol><p class="subtitle">Аккаунты и коды создаёт министерство. При потере кода запросите перевыпуск у отправителя. При обновлении доступа работы, баллы и достижения участника сохраняются.</p></details><div class="section-heading"><h2>Последние поступления</h2><button class="btn outline" data-go="directorInbox">Все входящие</button></div>${packageCards(packets.slice(0, 3), false)}`
  );
}
function directorInbox() {
  return packageListPage(false);
}
function directorAccounts(role) {
  const visible = (admin?.accounts || []).filter(
    (a) =>
      a.role === role &&
      (!directorOrganization || a.organizationId === directorOrganization) &&
      a.name.toLocaleLowerCase('ru').includes(directorQuery.toLocaleLowerCase('ru'))
  );
  return (
    heading(
      role === 'teacher' ? 'Учителя' : 'Ученики',
      'Реестр участников вашей организации. Коды доступны во входящих пакетах.',
      '<button class="btn outline" data-go="directorInbox">Входящие списки</button>'
    ) +
    `<div class="filters"><input id="director-search" aria-label="Поиск по ФИО" placeholder="Поиск по ФИО" value="${esc(directorQuery)}"><select id="director-organization" aria-label="Образовательная организация"><option value="">Все организации</option>${(admin?.organizations || []).map((o) => `<option value="${esc(o.id)}" ${directorOrganization === o.id ? 'selected' : ''}>${esc(o.name)}</option>`).join('')}</select></div><section class="card">${visible.map((a) => `<article class="director-account-row"><span class="tile">♙</span><div class="task-body"><h3>${esc(a.name)}</h3><div class="meta"><span>${esc(a.school)}</span><span>${esc(a.className)}</span><span class="pill ${a.status === 'active' ? 'green' : ''}">${a.status === 'legacy' ? 'Ожидает списка министерства' : a.status === 'active' ? 'Доступ выдан' : 'Пакет ещё не отправлен'}</span></div></div></article>`).join('') || empty('Профилей пока нет', 'Они появятся после обработки списка министерством.')}</section>`
  );
}
