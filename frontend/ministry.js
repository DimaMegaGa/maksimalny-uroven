let importSource = '',
  importXlsx = '',
  importPreview = null;
const packageStatus = (p) =>
  p.status === 'draft'
    ? 'Черновик'
    : p.status === 'distributed'
      ? 'Распределён'
      : p.openedAt
        ? 'Прочитан директором'
        : 'Доставлен · не прочитан';
const rosterTemplate =
  'ФИО;Роль;Класс\r\nИванов Иван Иванович;ученик;8А\r\nПетрова Анна Сергеевна;учитель;\r\n';

function administrativeProfile() {
  const user = currentUser();
  const schools = isMinistry()
    ? [...new Set((admin?.recipients || []).map((r) => r.school))]
    : (admin?.organizations || []).map((o) => o.name);
  return (
    heading(
      'Мой аккаунт',
      'Доступ и образовательные организации.',
      '<button class="btn outline" data-go="home">В кабинет</button>'
    ) +
    `<section class="card admin-profile"><div class="admin-profile-identity">${avatar(user)}<div><h2>${esc(user.name)}</h2><p class="subtitle">${isMinistry() ? 'Министерство' : 'Директор'}</p></div></div><h3>Образовательные организации</h3><div class="subject-tags">${schools.map((name) => `<span class="pill">${esc(name)}</span>`).join('') || '<p class="subtitle">Организации ещё не назначены.</p>'}</div><button class="btn outline" id="admin-profile-logout">Выйти из аккаунта</button></section>`
  );
}

function downloadText(text, name, type = 'text/plain') {
  const url = URL.createObjectURL(new Blob(['\ufeff', text], { type: type + ';charset=utf-8' }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function ministryHome() {
  const packets = admin?.packages || [],
    recipients = admin?.recipients || [];
  const schools = [...new Set(recipients.map((r) => r.school))];
  return (
    heading(
      'Управление доступом',
      'Учётные записи участников и доставка персональных кодов в образовательные организации.',
      '<button class="btn" data-go="ministryUpload">+ Загрузить список</button>'
    ) +
    `<div class="metrics">${metric('<img class="ministry-org-icon subject-symbol subject-symbol--line" src="/assets/school.png" width="30" height="30" alt="" aria-hidden="true">', '', 'Организаций', schools.length)}${metric('<img class="ministry-org-icon subject-symbol subject-symbol--line" src="/assets/edit-draft.png" width="30" height="30" alt="" aria-hidden="true">', '', 'Черновиков', packets.filter((p) => p.status === 'draft').length, 'ministryPackages')}${metric('✓', 'green', 'Отправлено пакетов', packets.filter((p) => p.status !== 'draft').length, 'ministryPackages')}</div><section class="card director-organizations"><div class="section-heading"><h2>Образовательные организации</h2><span class="pill">${schools.length}</span></div><div class="subject-tags">${schools.map((name) => `<span class="pill">${esc(name)}</span>`).join('') || '<p class="subtitle">Назначенные организации появятся здесь.</p>'}</div></section><div class="section-heading"><h2>Последние пакеты</h2><button class="btn outline" data-go="ministryPackages">Все отправления</button></div>${packageCards(packets.slice(0, 3), true)}<details class="card portal-guide"><summary>Порядок подготовки и выдачи доступа</summary><ol><li>Загрузите CSV или XLSX со столбцами ФИО, Роль и Класс. Укажите организацию и директора.</li><li>Проверьте строки и сформируйте пакет с персональными кодами.</li><li>Откройте список и инструкцию, затем отправьте пакет директору.</li><li>Отслеживайте получение и распределение доступа в разделе «Отправления».</li></ol></details>`
  );
}

function packageCards(packets, ministry) {
  return `<section class="package-list">${
    packets
      .map(
        (p) =>
          `<article class="card package-card"><div class="package-heading"><span class="tile">${documentSymbol()}</span><div><h3>${esc(p.title)}</h3><p class="subtitle">${esc(p.school)} · ${p.rowCount} ${p.rowCount % 100 >= 11 && p.rowCount % 100 <= 14 ? 'участников' : p.rowCount % 10 === 1 ? 'участник' : p.rowCount % 10 >= 2 && p.rowCount % 10 <= 4 ? 'участника' : 'участников'}</p></div><span class="pill ${p.status === 'distributed' ? 'green' : ''}">${packageStatus(p)}</span></div><p class="subtitle">${ministry ? 'Получатель: ' + esc(p.director) : 'Отправитель: кабинет министерства'} · ${dateLabel(p.sentAt || p.createdAt)}</p><ol class=delivery-timeline>${[
            ['Создан', p.createdAt],
            ['Отправлен', p.sentAt],
            ['Прочитан', p.openedAt],
            ['Распределён', p.distributedAt],
          ]
            .map(
              ([name, date]) =>
                `<li class="${date ? 'done' : ''}">${name}${date ? ' · ' + dateLabel(date) : ''}</li>`
            )
            .join(
              ''
            )}</ol><div class="package-actions"><button class="btn outline" data-package-open="${esc(p.id)}">Открыть список и инструкцию</button>${ministry && p.status === 'draft' ? `<button class="btn" data-package-send="${esc(p.id)}">Отправить директору</button>` : !ministry && p.status !== 'distributed' ? `<button class="btn soft" data-package-distribute="${esc(p.id)}" ${p.openedAt ? '' : 'disabled'}>Отметить распределённым</button>` : ''}</div></article>`
      )
      .join('') ||
    empty(
      ministry ? 'Отправлений пока нет' : 'Входящих пока нет',
      ministry
        ? 'Загрузите таблицу и сформируйте первый пакет.'
        : 'Когда министерство отправит список, он появится здесь вместе с уведомлением.'
    )
  }</section>`;
}

function pagination(page, total, type) {
  const pages = Math.ceil(total / 20);
  return pages > 1
    ? `<div class="pagination"><button class="btn outline" data-${type}-page="${page - 1}" ${page ? '' : 'disabled'}>Назад</button><span>${page + 1} из ${pages}</span><button class="btn outline" data-${type}-page="${page + 1}" ${page + 1 < pages ? '' : 'disabled'}>Далее</button></div>`
    : '';
}
function packageListPage(ministry) {
  const rows = (admin?.packages || []).filter(
    (p) =>
      (p.title + ' ' + p.school + ' ' + p.director)
        .toLocaleLowerCase('ru')
        .includes(packetQuery.toLocaleLowerCase('ru')) &&
      (!packetStage ||
        (packetStage === 'opened'
          ? p.openedAt && p.status !== 'distributed'
          : packetStage === 'sent'
            ? p.status === 'sent' && !p.openedAt
            : p.status === packetStage))
  );
  packetPage = Math.min(packetPage, Math.max(0, Math.ceil(rows.length / 20) - 1));
  return (
    heading(
      ministry ? 'Отправления' : 'Входящие от министерства',
      'Статус доставки и распределения персонального доступа.',
      ministry ? '<button class="btn" data-go="ministryUpload">+ Загрузить таблицу</button>' : ''
    ) +
    `<div class="filters"><input id="packet-query" placeholder="Название, организация, директор" aria-label="Поиск отправлений" value="${esc(packetQuery)}"><select id="packet-stage" aria-label="Статус отправления">${[
      ['', 'Все статусы'],
      ['draft', 'Черновики'],
      ['sent', 'Не прочитаны'],
      ['opened', 'Прочитаны'],
      ['distributed', 'Распределены'],
    ]
      .map(([v, l]) => `<option value="${v}" ${v === packetStage ? 'selected' : ''}>${l}</option>`)
      .join('')}</select></div><p class="subtitle">Найдено: ${rows.length}</p>` +
    packageCards(rows.slice(packetPage * 20, packetPage * 20 + 20), ministry) +
    pagination(packetPage, rows.length, 'packet')
  );
}

function ministryUpload() {
  const recipients = admin?.recipients || [];
  return (
    heading(
      'Загрузка списка',
      'Один пакет — одна организация и один директор. До 200 участников.',
      '<button class="btn outline" id="roster-template">Скачать шаблон CSV</button>'
    ) +
    `<section class="card create-card"><form id="ministry-import-form"><label>Организация и директор<select name="recipient" required>${recipients.map((r, i) => `<option value="${i}">${esc(r.school)} — ${esc(r.director)}</option>`).join('')}</select></label><label>Название пакета<input name="title" required maxlength="120" value="Доступ к школьной платформе"></label><ol class="import-steps"><li>1. Загрузите таблицу</li><li>2. Сопоставьте и проверьте</li><li>3. Создайте и отправьте</li></ol><label>Таблица CSV или Excel<input id="roster-file" type="file" accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" required></label><div id="column-mapping"></div><p class="subtitle">Столбцы: ФИО, Роль, Класс. Роли: ученик / учитель. Для учителя класс пустой. CSV UTF-8 и Windows-1251, разделители ; , и табуляция. Excel: первый лист, до 2 МБ. CSV: до 300 КБ. Коды генерируются платформой; загружайте только исходный список.</p><label>Сопроводительное сообщение<textarea name="instructions" rows="4" maxlength="8000" placeholder="Необязательно: сообщение будет добавлено к стандартной инструкции"></textarea></label><button class="btn outline" id="preview-roster" type="button" ${recipients.length ? '' : 'disabled'}>Проверить таблицу</button><div id="roster-preview" aria-live="polite"></div><p class="form-error" role="alert"></p><button class="btn" id="create-package" type="submit" disabled>Создать аккаунты и пакет с кодами</button><p class="subtitle">До отправки новые аккаунты неактивны. Повторная загрузка созданных профилей блокируется. Участников с полностью одинаковыми ФИО, ролью и классом нужно сверить отдельно.</p>${recipients.length ? '' : '<p class="notice">Организация и директор ещё не назначены. Обратитесь к администратору платформы.</p>'}</form></section>`
  );
}

function ministryAccounts() {
  const all = admin?.accounts || [],
    schools = [...new Set(all.map((a) => a.school))];
  const rows = all.filter(
    (a) =>
      (a.name + ' ' + a.className)
        .toLocaleLowerCase('ru')
        .includes(registryQuery.toLocaleLowerCase('ru')) &&
      (!registrySchool || a.school === registrySchool) &&
      (!registryRole || a.role === registryRole) &&
      (!registryStatus || Boolean(a.active) === (registryStatus === 'active'))
  );
  registryPage = Math.min(registryPage, Math.max(0, Math.ceil(rows.length / 20) - 1));
  const select = (id, value, options) =>
    `<select id="${id}" aria-label="${id === 'registry-role' ? 'Роль' : id === 'registry-status' ? 'Состояние доступа' : 'Организация'}">${options.map(([v, l]) => `<option value="${esc(v)}" ${v === value ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select>`;
  return (
    heading(
      'Аккаунты',
      'Замена кода оформляется отдельным пакетом. Старый код действует до его отправки.'
    ) +
    `<div class="filters registry-filters"><input id="registry-query" aria-label="Поиск аккаунтов" placeholder="ФИО или класс" value="${esc(registryQuery)}">${select('registry-school', registrySchool, [['', 'Все организации'], ...schools.map((n) => [n, n])])}${select(
      'registry-role',
      registryRole,
      [
        ['', 'Все роли'],
        ['teacher', 'Учителя'],
        ['student', 'Ученики'],
      ]
    )}${select('registry-status', registryStatus, [
      ['', 'Любой статус'],
      ['active', 'Доступ открыт'],
      ['inactive', 'Ожидает отправки'],
    ])}</div><p class="subtitle">Найдено: ${rows.length} из ${all.length}</p><section class="card">${
      rows
        .slice(registryPage * 20, registryPage * 20 + 20)
        .map(
          (a) =>
            `<article class="director-account-row"><div class="task-body"><h3>${esc(a.name)}</h3><p class="subtitle">${esc(a.school)} · ${a.role === 'teacher' ? 'Учитель' : 'Ученик · ' + esc(a.className)}</p></div>${a.active ? `<button class="btn outline" data-ministry-reissue="${esc(a.id)}">Перевыпустить код</button>` : '<span class="pill">Ожидает отправки</span>'}</article>`
        )
        .join('') || empty('Аккаунты не найдены', 'Измените фильтры или загрузите список.')
    }</section>` +
    pagination(registryPage, rows.length, 'registry')
  );
}

async function openDeliveryPackage(id) {
  try {
    const packet = await api('packages/open', { packageId: id });
    await refreshFromServer(true);
    showModal(
      `<div class="sheet-header"><h2>${esc(packet.title)}</h2><button class="sheet-close" data-close aria-label="Закрыть">×</button></div><div class="issued-code-body"><p class="notice">Передавайте каждому участнику только его строку. Скачанный файл храните в защищённом месте.${packet.status === 'draft' ? ' Новые аккаунты станут доступны после отправки пакета.' : ''}</p><div class="package-actions"><button class="btn" id="download-package">Скачать таблицу CSV</button><button class="btn outline" id="download-instructions">Скачать инструкцию</button></div><div class="package-table-wrap"><table class="package-table"><thead><tr><th>ФИО</th><th>Роль / класс</th><th>Персональный код</th></tr></thead><tbody>${packet.rows.map((r) => `<tr><td>${esc(r.name)}</td><td>${r.role === 'teacher' ? 'Учитель' : 'Ученик · ' + esc(r.className)}</td><td>${r.current ? `<input type="password" class="package-code" aria-label="Код: ${esc(r.name)}" readonly value="${esc(r.code)}" autocomplete="off" spellcheck="false"><button type="button" class="link" data-toggle-code>Показать</button>` : '<span class="pill">Код заменён</span>'}</td></tr>`).join('')}</tbody></table></div><h3>Инструкция директору</h3><div class="package-instructions">${esc(packet.instructions)}</div><button class="btn outline" data-close>Закрыть список</button></div>`,
      'task-sheet credential-sheet package-sheet'
    );
    $$('[data-toggle-code]', modal).forEach(
      (b) =>
        (b.onclick = () => {
          const input = b.previousElementSibling;
          input.type = input.type === 'password' ? 'text' : 'password';
          b.textContent = input.type === 'password' ? 'Показать' : 'Скрыть';
        })
    );
    const cell = (value) =>
      '"' +
      String(value ?? '')
        .replace(/^[\s]*[=+@-]/, (m) => "'" + m)
        .replace(/"/g, '""') +
      '"';
    $('#download-package').onclick = () =>
      downloadText(
        [
          'ФИО;Роль;Класс;Организация;Персональный код;Статус',
          ...packet.rows.map((r) =>
            [
              r.name,
              r.role === 'teacher' ? 'учитель' : 'ученик',
              r.className,
              r.school,
              r.current ? r.code : '',
              r.current ? 'актуален' : 'код заменён',
            ]
              .map(cell)
              .join(';')
          ),
        ].join('\r\n'),
        'accounts-' + packet.id + '.csv',
        'text/csv'
      );
    $('#download-instructions').onclick = () =>
      downloadText(packet.instructions, 'instruction-' + packet.id + '.txt');
  } catch (error) {
    toast(error.message);
  }
}

async function performPackageAction(button, action) {
  const label = button.textContent;
  button.disabled = true;
  button.textContent = action === 'send' ? 'Отправляем…' : 'Сохраняем…';
  try {
    acceptState(
      await api('packages/' + action, {
        packageId: button.dataset[action === 'send' ? 'packageSend' : 'packageDistribute'],
      })
    );
    render();
    toast(action === 'send' ? 'Пакет доставлен директору' : 'Пакет отмечен как распределённый');
  } catch (error) {
    toast(error.message);
    button.disabled = false;
    button.textContent = label;
  }
}

function bindProvisioning() {
  $('#admin-profile-logout')?.addEventListener('click', logout);
  $$('[data-package-open]', app).forEach(
    (b) => (b.onclick = () => openDeliveryPackage(b.dataset.packageOpen))
  );
  $$('[data-package-send]', app).forEach(
    (b) => (b.onclick = () => performPackageAction(b, 'send'))
  );
  $$('[data-package-distribute]', app).forEach(
    (b) => (b.onclick = () => performPackageAction(b, 'distribute'))
  );
  $('#roster-template')?.addEventListener('click', () =>
    downloadText(rosterTemplate, 'roster-template.csv', 'text/csv')
  );
  $('#director-organization')?.addEventListener('change', (e) => {
    directorOrganization = e.target.value;
    render();
  });
  $('#director-search')?.addEventListener('input', (e) => {
    directorQuery = e.target.value;
    const pos = e.target.selectionStart;
    render();
    $('#director-search').focus();
    $('#director-search').setSelectionRange(pos, pos);
  });
  const form = $('#ministry-import-form');
  if (form) {
    importSource = '';
    importXlsx = '';
    importPreview = null;
    let previewVersion = 0,
      fileLoading = false;
    const invalidate = () => {
      previewVersion++;
      importPreview = null;
      $('#create-package', form).disabled = true;
      $('#roster-preview', form).innerHTML = '';
    };
    form.oninput = (e) => {
      if (e.target.id !== 'roster-file') invalidate();
    };
    form.onchange = (e) => {
      if (e.target.id !== 'roster-file') invalidate();
    };
    const fields = () => {
      const data = Object.fromEntries(new FormData(form)),
        recipient = (admin?.recipients || [])[Number(data.recipient)];
      const mapping = {};
      for (const key of ['ФИО', 'Роль', 'Класс'])
        mapping[key] = form.querySelector(`[data-column="${key}"]`)?.value || key;
      return {
        title: data.title,
        instructions: data.instructions,
        ...recipient,
        ...(importXlsx ? { xlsx: importXlsx } : { csv: importSource }),
        mapping,
      };
    };
    $('#roster-file').onchange = async () => {
      invalidate();
      const version = previewVersion;
      importSource = '';
      importXlsx = '';
      $('#column-mapping').innerHTML = '';
      $('.form-error', form).textContent = '';
      const file = $('#roster-file').files[0];
      if (!file) return;
      fileLoading = true;
      $('#preview-roster').disabled = true;
      try {
        const xlsx = /\.xlsx$/i.test(file.name);
        if (file.size > (xlsx ? 2000000 : 300000))
          throw new Error(
            xlsx ? 'Excel должен быть не больше 2 МБ' : 'CSV должен быть не больше 300 КБ'
          );
        const buffer = await file.arrayBuffer();
        let source;
        if (xlsx) {
          const bytes = new Uint8Array(buffer);
          let text = '';
          for (let i = 0; i < bytes.length; i += 8192)
            text += String.fromCharCode(...bytes.subarray(i, i + 8192));
          source = { xlsx: btoa(text) };
        } else {
          let text;
          try {
            text = new TextDecoder('utf-8', { fatal: true }).decode(buffer);
          } catch {
            text = new TextDecoder('windows-1251').decode(buffer);
          }
          source = { csv: text };
        }
        const info = await api('ministry/inspect', source);
        if (version !== previewVersion || !form.isConnected) return;
        importSource = source.csv || '';
        importXlsx = source.xlsx || '';
        $('#column-mapping').innerHTML =
          `<h3>Сопоставьте столбцы · ${info.count} строк</h3><div class="filters">${['ФИО', 'Роль', 'Класс'].map((key) => `<label>${key}<select data-column="${key}" required>${info.columns.map((c) => `<option value="${esc(c)}" ${c.trim().toLocaleLowerCase('ru') === key.toLocaleLowerCase('ru') ? 'selected' : ''}>${esc(c)}</option>`).join('')}</select></label>`).join('')}</div><p class="subtitle">Лишние столбцы не загружаются в аккаунты. Затем нажмите «Проверить таблицу».</p>`;
      } catch (error) {
        $('.form-error', form).textContent = error.message;
      } finally {
        fileLoading = false;
        $('#preview-roster').disabled = false;
      }
    };
    $('#preview-roster').onclick = async (e) => {
      invalidate();
      $('.form-error', form).textContent = '';
      if (fileLoading || (!importSource && !importXlsx)) {
        $('.form-error', form).textContent = 'Выберите и дождитесь чтения CSV или XLSX';
        return;
      }
      const version = previewVersion;
      e.target.disabled = true;
      processing = true;
      try {
        const preview = await api('ministry/preview', fields());
        if (version !== previewVersion || !form.isConnected) return;
        importPreview = preview;
        $('#roster-preview').innerHTML =
          `<h3>Проверено: ${preview.count}</h3>${preview.errors.length ? `<ul class="import-errors">${preview.errors.map((r) => `<li>Строка ${r.line}: ${esc(r.message)}</li>`).join('')}</ul><button type="button" class="btn outline" id="download-import-errors">Скачать отчёт об ошибках</button>` : '<p class="notice">Ошибок нет. Проверьте ФИО и классы перед созданием.</p>'}<details class="roster-sample"><summary>Все строки (${preview.rows.length})</summary>${preview.rows.map((r) => `<p>${esc(r.name)} · ${r.role === 'teacher' ? 'Учитель' : 'Ученик · ' + esc(r.className)}${r.legacyId ? ' · существующий профиль' : ''}</p>`).join('')}</details>`;
        $('#download-import-errors')?.addEventListener('click', () =>
          downloadText(
            preview.errors.map((r) => 'Строка ' + r.line + ': ' + r.message).join('\r\n'),
            'roster-errors.txt'
          )
        );
        $('#create-package').disabled = !!preview.errors.length || !preview.count;
      } catch (error) {
        $('.form-error', form).textContent = error.message;
      } finally {
        processing = false;
        e.target.disabled = false;
      }
    };
    form.onsubmit = async (e) => {
      e.preventDefault();
      if (!importPreview || importPreview.errors.length || processing) return;
      processing = true;
      $('#create-package').disabled = true;
      $('#create-package').textContent = 'Создаём аккаунты и защищаем коды…';
      try {
        acceptState(await api('ministry/import', fields()));
        importSource = '';
        importPreview = null;
        location.hash = 'ministryPackages';
        render();
        toast('Пакет создан. Проверьте и отправьте директору.');
      } catch (error) {
        $('.form-error', form).textContent = error.message;
        $('#create-package', form).disabled = false;
        $('#create-package', form).textContent = 'Создать аккаунты и пакет с кодами';
      } finally {
        processing = false;
      }
    };
  }
  $$('[data-ministry-reissue]', app).forEach(
    (button) =>
      (button.onclick = () => {
        const account = admin.accounts.find((a) => a.id === button.dataset.ministryReissue),
          recipients = (admin.recipients || []).filter((r) => r.school === account.school);
        showModal(
          `<div class="sheet-header"><h2>Замена персонального кода</h2><button class="sheet-close" data-close aria-label="Закрыть">×</button></div><form id="reissue-form" class="issued-code-body"><h3>${esc(account.name)}</h3><label>Получатель<select name="recipient">${recipients.map((r, i) => `<option value="${i}">${esc(r.school)} — ${esc(r.director)}</option>`).join('')}</select></label><p>Будет создан черновик с новым кодом. При его отправке прежний код и сеансы участника будут отозваны.</p><button class="btn" ${recipients.length ? '' : 'disabled'}>Создать пакет замены</button><p class="form-error" role="alert"></p></form>`,
          'task-sheet'
        );
        $('#reissue-form').onsubmit = async (e) => {
          e.preventDefault();
          const b = $('button.btn', e.target);
          b.disabled = true;
          try {
            acceptState(
              await api('ministry/reissue', {
                userId: account.id,
                ...recipients[Number(e.target.elements.recipient.value)],
              })
            );
            closeModal();
            location.hash = 'ministryPackages';
            render();
          } catch (error) {
            $('.form-error', e.target).textContent = error.message;
            b.disabled = false;
          }
        };
      })
  );
}
