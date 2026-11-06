'use strict';
let taskClassChoice = '',
  taskLearnerChoice = '',
  statsDays = 30;
let registryQuery = '',
  registrySchool = '',
  registryRole = '',
  registryStatus = '',
  registryPage = 0;
let packetQuery = '',
  packetStage = '',
  packetPage = 0;
function nextActions() {
  if (!currentUser() || isDirector() || isMinistry()) return '';
  let title = '',
    description = '',
    action = '';
  if (isTeacher()) {
    const work = db.submissions
      .filter((s) => s.status === 'pending' && myTasks().some((t) => t.id === s.taskId))
      .sort((a, b) => a.createdAt - b.createdAt)[0];
    const request = exchangeRequestsPending()[0];
    if (work) {
      title = 'Работа ждёт вашей проверки';
      description = db.tasks.find((t) => t.id === work.taskId)?.title;
      action = `<button class="btn" data-review="${work.id}">Проверить работу</button>`;
    } else if (request) {
      title = 'Новый запрос на оценку';
      description = request.subject;
      action = '<button class="btn" data-go="exchange">Открыть запросы</button>';
    } else {
      title = 'Всё проверено';
      description = 'Можно подготовить следующее задание для класса.';
      action = '<button class="btn soft" data-go="create">Создать задание</button>';
    }
  } else {
    const revision = myTasks().find((t) => !t.archived && taskStatus(t) === 'rejected');
    const nearest = myTasks()
      .filter((t) => !t.archived && taskStatus(t) === 'available')
      .sort((a, b) => a.deadline.localeCompare(b.deadline))[0];
    if (revision) {
      title = 'Работа на доработке';
      description = mySubmission(revision.id)?.teacherComment || revision.title;
      action = `<button class="btn" data-detail="${revision.id}">Посмотреть замечания</button>`;
    } else if (nearest) {
      title = nearest.deadline < today() ? 'Проверь срок задания' : 'Ближайшее задание';
      description = nearest.title + ' · ' + dateLabel(nearest.deadline);
      action = `<button class="btn" data-detail="${nearest.id}">Открыть задание</button>`;
    } else {
      title = 'Ты всё отправил';
      description = 'Результаты и комментарии учителей доступны в истории.';
      action = '<button class="btn soft" data-go="history">Открыть историю</button>';
    }
  }
  return `<section class="card next-action" aria-label="Следующее действие"><div><small>Что сделать дальше</small><h2>${esc(title)}</h2><p>${esc(description)}</p></div>${action}</section>`;
}
function exchangeRequestsPending() {
  return db.exchanges.filter((r) => r.teacherId === currentUser()?.id && r.status === 'pending');
}
function taskTools(task) {
  if (!isTeacher()) return '';
  const hasAnswers = db.submissions.some((s) => s.taskId === task.id);
  return `<div class="task-tools">${!task.archived && !hasAnswers ? `<button class="link" data-task-edit="${task.id}">Исправить условия</button>` : ''}<button class="link" data-task-archive="${task.id}">${task.archived ? 'Вернуть из архива' : 'В архив'}</button></div>`;
}
function teacherFilters() {
  if (!isTeacher()) return '';
  const classes = [...new Set(students().map((u) => u.className))].sort((a, b) =>
    a.localeCompare(b, 'ru', { numeric: true })
  );
  return `<div class="filters"><select id="task-class" aria-label="Класс"><option value="">Все классы</option>${classes.map((c) => `<option ${c === taskClassChoice ? 'selected' : ''}>${esc(c)}</option>`).join('')}</select><input id="task-learner" aria-label="Ученик" placeholder="Найти ученика по ФИО" value="${esc(taskLearnerChoice)}"></div>`;
}
function matchingLearner(row) {
  const user = db.users.find((u) => u.id === row.userId);
  return (
    user &&
    (!taskClassChoice || classKey(user.className) === classKey(taskClassChoice)) &&
    user.name.toLocaleLowerCase('ru').includes(taskLearnerChoice.toLocaleLowerCase('ru'))
  );
}
function openNotificationTarget(row) {
  const [kind, id] = (row.eventId || '').split(':');
  const submission = db.submissions.find((s) => s.id === (row.submissionId || id));
  const task = db.tasks.find((t) => t.id === (kind === 'task' ? id : submission?.taskId));
  if (row.type === 'level') {
    achievementDialog(currentUser().id);
    return;
  }
  if (task) {
    if (isTeacher() && submission) reviewDialog(submission.id);
    else taskDetail(task.id);
    return;
  }
  go(
    row.target,
    row.type === 'reward' ? 'completed' : row.type === 'review' ? 'pending' : undefined
  );
}
function workspaceStats() {
  const all = myTasks(),
    cutoff = Date.now() - statsDays * 86400000;
  const rows = db.submissions.filter(
    (s) => all.some((t) => t.id === s.taskId) && s.createdAt >= cutoff && matchingLearner(s)
  );
  const approved = rows.filter((s) => s.status === 'approved'),
    pending = rows.filter((s) => s.status === 'pending'),
    returned = rows.filter((s) => s.status === 'rejected' && s.reviewOutcome !== 'rejected');
  const checked = rows.filter((s) => s.checkedAt),
    hours = checked.length
      ? Math.round(
          checked.reduce((n, s) => n + Math.max(0, s.checkedAt - s.createdAt), 0) /
            checked.length /
            3600000
        )
      : null;
  const days = Array.from({ length: 7 }, (_, i) => {
    const d = new Date();
    d.setDate(d.getDate() - 6 + i);
    const start = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
    return {
      label: d.toLocaleDateString('ru', { weekday: 'short' }),
      count: rows.filter((s) => s.createdAt >= start && s.createdAt < start + 86400000).length,
    };
  });
  const maximum = Math.max(1, ...days.map((d) => d.count));
  return (
    heading(
      'Статистика',
      'Показатели рассчитаны по работам ваших учеников.',
      '<button class="btn outline" id="export-results">Скачать результаты CSV</button>'
    ) +
    `<div class="filters"><select id="stats-period" aria-label="Период">${[7, 30, 90, 365].map((n) => `<option value="${n}" ${statsDays === n ? 'selected' : ''}>За ${n} дней</option>`).join('')}</select></div>${teacherFilters()}<div class="metrics">${metric('✓', 'green', 'Принято работ', approved.length)}${metric('◷', 'gold', 'Ожидают проверки', pending.length)}${metric(revisionSymbol(), '', 'На доработке', returned.length)}</div><section class="card stats-summary"><p>Доля принятых работ: <strong>${rows.length ? Math.round((approved.length / rows.length) * 100) + '%' : 'пока нет данных'}</strong></p><p>Среднее ожидание решения: <strong>${hours === null ? 'пока нет данных' : hours < 1 ? 'меньше часа' : hours + ' ч'}</strong></p><h2>Поступление работ за неделю</h2><div class="activity-chart">${days.map((d) => `<div><strong>${d.count}</strong><span style="height:${Math.max(3, (d.count / maximum) * 90)}px"></span><small>${d.label}</small></div>`).join('')}</div></section><section class="card"><h2>Работы учеников</h2>${
      rows
        .map((s) => {
          const task = all.find((t) => t.id === s.taskId),
            user = db.users.find((u) => u.id === s.userId);
          return `<article class="task"><div class="task-body"><h3>${esc(task.title)}</h3><p class="meta">${esc(user?.name)} · ${esc(user?.className)} · ${s.status === 'rejected' && s.reviewOutcome === 'rejected' ? 'Отклонено' : statusText[s.status]}</p></div><button class="btn outline" data-review="${s.id}">Открыть работу</button></article>`;
        })
        .join('') || empty('Работ за этот период нет', 'Измените период или фильтры.')
    }</section>`
  );
}
function exportResults() {
  const tasks = myTasks(),
    cutoff = Date.now() - statsDays * 86400000;
  const rows = [
    [
      'Ученик',
      'Класс',
      'Задание',
      'Предмет',
      'Результат',
      'Баллы',
      'Отправлено',
      'Проверено',
      'Комментарий',
    ],
  ];
  for (const s of db.submissions.filter(
    (s) => tasks.some((t) => t.id === s.taskId) && s.createdAt >= cutoff && matchingLearner(s)
  )) {
    const t = tasks.find((t) => t.id === s.taskId),
      u = db.users.find((u) => u.id === s.userId);
    rows.push([
      u?.name,
      u?.className,
      t.title,
      t.subject,
      s.status === 'rejected' && s.reviewOutcome === 'rejected'
        ? 'Отклонено'
        : statusText[s.status],
      s.status === 'approved' ? t.points : 0,
      new Date(s.createdAt).toISOString(),
      s.checkedAt ? new Date(s.checkedAt).toISOString() : '',
      s.teacherComment || '',
    ]);
  }
  const cell = (value) =>
    '"' +
    String(value ?? '')
      .replace(/^[\s]*[=+@-]/, (m) => "'" + m)
      .replace(/"/g, '""') +
    '"';
  downloadText(rows.map((row) => row.map(cell).join(';')).join('\r\n'), 'results.csv', 'text/csv');
}
function editTaskDialog(identity) {
  const task = myTasks().find((t) => t.id === identity);
  if (!task || !isTeacher()) return;
  showModal(
    `<div class="sheet-header"><h2>Исправить условия</h2><button class="sheet-close" data-close aria-label="Закрыть">×</button></div><form id="edit-task-form" class="issued-code-body"><p class="notice">Редактирование доступно до первой сдачи. Баллы и адресаты сохраняются.</p><label>Название<input name="title" maxlength="120" required value="${esc(task.title)}"></label><label>Описание<textarea name="description" maxlength="3000" required>${esc(task.description)}</textarea></label><label>Как выполнить<textarea name="instructions" maxlength="2000">${esc(task.instructions)}</textarea></label><button class="btn">Сохранить условия</button><p class="form-error" role="alert"></p></form>`,
    'task-sheet'
  );
  const form = $('#edit-task-form');
  bindDraft(form, 'edit-task:' + identity, ['title', 'description', 'instructions']);
  form.onsubmit = async (e) => {
    e.preventDefault();
    const button = $('.btn', form);
    button.disabled = true;
    try {
      acceptState(
        await api('tasks/update', { taskId: identity, ...Object.fromEntries(new FormData(form)) })
      );
      clearDraft('edit-task:' + identity);
      closeModal();
      render();
      toast('Условия обновлены');
    } catch (error) {
      $('.form-error', form).textContent = error.message;
    } finally {
      button.disabled = false;
    }
  };
}
function bindWorkspaceExtras() {
  bindDatePickers(app);
  if (!$('#connection-status'))
    app.insertAdjacentHTML(
      'beforebegin',
      '<div id="connection-status" class="connection-banner" role="status" hidden></div>'
    );
  connectionState(connectionAvailable);
  if (page() === 'home') {
    $('.heading', app)?.insertAdjacentHTML('afterend', nextActions());
    $$('[data-detail]', app).forEach((b) => (b.onclick = () => taskDetail(b.dataset.detail)));
    $$('[data-review]', app).forEach((b) => (b.onclick = () => reviewDialog(b.dataset.review)));
    $$('[data-go]', app).forEach((b) => (b.onclick = () => go(b.dataset.go, b.dataset.taskTab)));
  }
  if (page() === 'tasks') {
    $('.heading', app)?.insertAdjacentHTML(
      'beforeend',
      '<button class="btn outline" id="export-calendar">Сроки в календарь</button>'
    );
    $('#export-calendar').onclick = () => {
      const data = calendarFile(
        myTasks().filter((t) => isTeacher() || taskStatus(t) !== 'approved'),
        'Школьные задания'
      );
      const url = URL.createObjectURL(new Blob([data], { type: 'text/calendar;charset=utf-8' }));
      const link = document.createElement('a');
      link.href = url;
      link.download = 'school-tasks.ics';
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    };
  }
  $$('[data-task-edit]', app).forEach(
    (b) => (b.onclick = () => editTaskDialog(b.dataset.taskEdit))
  );
  $$('[data-task-archive]', app).forEach(
    (b) =>
      (b.onclick = async () => {
        const task = myTasks().find((t) => t.id === b.dataset.taskArchive);
        b.disabled = true;
        try {
          acceptState(await api('tasks/update', { taskId: task.id, archived: !task.archived }));
          render();
          toast(task.archived ? 'Задание возвращено' : 'Задание в архиве. История сохранена.');
        } catch (e) {
          toast(e.message);
          b.disabled = false;
        }
      })
  );
  $('#task-class')?.addEventListener('change', (e) => {
    taskClassChoice = e.target.value;
    render();
  });
  $('#task-learner')?.addEventListener('input', (e) => {
    taskLearnerChoice = e.target.value;
    const pos = e.target.selectionStart;
    render();
    $('#task-learner').focus();
    $('#task-learner').setSelectionRange(pos, pos);
  });
  $('#stats-period')?.addEventListener('change', (e) => {
    statsDays = Number(e.target.value);
    render();
  });
  $('#export-results')?.addEventListener('click', exportResults);
  bindRegistryFilters();
}
function bindRegistryFilters() {
  for (const [id, set] of [
    ['registry-school', (v) => (registrySchool = v)],
    ['registry-role', (v) => (registryRole = v)],
    ['registry-status', (v) => (registryStatus = v)],
    ['packet-stage', (v) => (packetStage = v)],
  ])
    $('#' + id)?.addEventListener('change', (e) => {
      set(e.target.value);
      registryPage = 0;
      packetPage = 0;
      render();
    });
  for (const [id, set] of [
    ['registry-query', (v) => (registryQuery = v)],
    ['packet-query', (v) => (packetQuery = v)],
  ])
    $('#' + id)?.addEventListener('input', (e) => {
      set(e.target.value);
      registryPage = 0;
      packetPage = 0;
      const pos = e.target.selectionStart;
      render();
      $('#' + id).focus();
      $('#' + id).setSelectionRange(pos, pos);
    });
  $$('[data-registry-page]').forEach(
    (b) =>
      (b.onclick = () => {
        registryPage = Number(b.dataset.registryPage);
        render();
      })
  );
  $$('[data-packet-page]').forEach(
    (b) =>
      (b.onclick = () => {
        packetPage = Number(b.dataset.packetPage);
        render();
      })
  );
}

let activeDatePicker = null;
let datePickerEventsBound = false;
function bindDatePickers(root = document) {
  const iso = (d) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const parse = (s) => {
    const [y, m, d] = s.split('-').map(Number);
    return new Date(y, m - 1, d, 12);
  };
  if (!datePickerEventsBound) {
    datePickerEventsBound = true;
    document.addEventListener('pointerdown', (e) => {
      if (activeDatePicker && !activeDatePicker.host.contains(e.target)) activeDatePicker.close();
    });
    document.addEventListener('focusin', (e) => {
      if (activeDatePicker && !activeDatePicker.host.contains(e.target)) activeDatePicker.close();
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && activeDatePicker) {
        e.preventDefault();
        activeDatePicker.close(true);
      }
    });
  }
  root.querySelectorAll('input[type="date"]:not([data-calendar-ready])').forEach((input) => {
    input.dataset.calendarReady = 'true';
    const host = document.createElement('div');
    host.className = 'date-picker';
    input.before(host);
    host.append(input);
    input.classList.add('date-picker-native');
    input.tabIndex = -1;
    const trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.className = 'date-picker-trigger';
    trigger.setAttribute('aria-haspopup', 'dialog');
    trigger.setAttribute('aria-expanded', 'false');
    const popup = document.createElement('div');
    popup.className = 'date-picker-panel';
    popup.hidden = true;
    popup.id =
      'date-calendar-' +
      (input.id || input.name || 'date') +
      '-' +
      Math.random().toString(36).slice(2, 8);
    popup.setAttribute('role', 'dialog');
    popup.setAttribute('aria-label', 'Выбрать срок выполнения');
    trigger.setAttribute('aria-controls', popup.id);
    host.append(trigger, popup);
    const calendarIcon =
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="4"/><path d="M7 3v4M17 3v4M3 11h18M8 15h2M14 15h2"/></svg>';
    let view, focused;
    const allowed = (s) => (!input.min || s >= input.min) && (!input.max || s <= input.max);
    const limit = (s) =>
      input.min && s < input.min ? input.min : input.max && s > input.max ? input.max : s;
    const todayDate = () => iso(new Date());
    const update = () => {
      trigger.innerHTML = `<span>${input.value ? parse(input.value).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' }) : 'Выберите дату'}</span>${calendarIcon}`;
      trigger.classList.toggle('has-value', Boolean(input.value));
      trigger.setAttribute(
        'aria-label',
        'Срок выполнения: ' +
          (input.value ? parse(input.value).toLocaleDateString('ru-RU') : 'дата не выбрана')
      );
    };
    const close = (restoreFocus = false) => {
      popup.hidden = true;
      trigger.setAttribute('aria-expanded', 'false');
      if (activeDatePicker?.host === host) activeDatePicker = null;
      if (restoreFocus) trigger.focus();
    };
    const choose = (s) => {
      if (s && !allowed(s)) return;
      input.value = s;
      trigger.removeAttribute('aria-invalid');
      update();
      close(true);
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
    };
    const renderCalendar = (focusDay = false) => {
      const first = new Date(view.getFullYear(), view.getMonth(), 1, 12),
        offset = (first.getDay() + 6) % 7;
      const prevEnd = iso(new Date(view.getFullYear(), view.getMonth(), 0, 12));
      const nextStart = iso(new Date(view.getFullYear(), view.getMonth() + 1, 1, 12));
      const heading = view
        .toLocaleDateString('ru-RU', { month: 'long', year: 'numeric' })
        .replace(/\s*г\.$/, '');
      popup.innerHTML = `<div class="date-picker-heading"><span aria-live="polite">${heading}</span><div><button type="button" data-month="-1" aria-label="Предыдущий месяц" ${input.min && prevEnd < input.min ? 'disabled' : ''}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m14 6-6 6 6 6"/></svg></button><button type="button" data-month="1" aria-label="Следующий месяц" ${input.max && nextStart > input.max ? 'disabled' : ''}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m10 6 6 6-6 6"/></svg></button></div></div><div class="date-picker-week" aria-hidden="true">${['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'].map((d) => `<span>${d}</span>`).join('')}</div><div class="date-picker-days" role="group" aria-label="Дни месяца">${Array.from(
        { length: 42 },
        (_, i) => {
          const d = new Date(first.getFullYear(), first.getMonth(), i - offset + 1, 12),
            s = iso(d),
            selected = s === input.value;
          return `<button type="button" data-date="${s}" class="${d.getMonth() !== view.getMonth() ? 'outside ' : ''}${s === todayDate() ? 'today ' : ''}${selected ? 'selected' : ''}" aria-label="${d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' })}" aria-pressed="${selected}" ${s === todayDate() ? 'aria-current="date"' : ''} tabindex="${s === focused ? '0' : '-1'}" ${allowed(s) ? '' : 'disabled'}>${d.getDate()}</button>`;
        }
      ).join(
        ''
      )}</div><div class="date-picker-footer"><button type="button" data-clear>Очистить</button><button type="button" data-today ${allowed(todayDate()) ? '' : 'disabled'}>Сегодня</button></div>`;
      popup
        .querySelectorAll('[data-date]')
        .forEach((b) => (b.onclick = () => choose(b.dataset.date)));
      popup.querySelectorAll('[data-month]').forEach(
        (b) =>
          (b.onclick = () => {
            view = new Date(view.getFullYear(), view.getMonth() + Number(b.dataset.month), 1, 12);
            focused = limit(iso(view));
            renderCalendar(true);
          })
      );
      popup.querySelector('[data-clear]').onclick = () => choose('');
      popup.querySelector('[data-today]').onclick = () => choose(todayDate());
      if (focusDay) popup.querySelector(`[data-date="${focused}"]:not(:disabled)`)?.focus();
    };
    const open = () => {
      activeDatePicker?.close();
      focused = limit(input.value || todayDate());
      view = parse(focused);
      popup.hidden = false;
      trigger.setAttribute('aria-expanded', 'true');
      activeDatePicker = { host, close };
      renderCalendar(true);
    };
    trigger.onclick = () => (popup.hidden ? open() : close());
    trigger.onkeydown = (e) => {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        open();
      }
    };
    popup.onkeydown = (e) => {
      const button = e.target.closest('[data-date]');
      if (!button) return;
      const delta = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[e.key];
      if (delta === undefined && !['Home', 'End', 'PageUp', 'PageDown'].includes(e.key)) return;
      e.preventDefault();
      const d = parse(button.dataset.date);
      if (delta !== undefined) d.setDate(d.getDate() + delta);
      else if (e.key === 'Home') d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
      else if (e.key === 'End') d.setDate(d.getDate() + 6 - ((d.getDay() + 6) % 7));
      else {
        const day = d.getDate();
        d.setDate(1);
        d.setMonth(d.getMonth() + (e.key === 'PageUp' ? -1 : 1));
        d.setDate(Math.min(day, new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate()));
      }
      focused = limit(iso(d));
      view = parse(focused);
      renderCalendar(true);
    };
    input.addEventListener('input', update);
    input.addEventListener('change', update);
    input.addEventListener('invalid', (e) => {
      e.preventDefault();
      trigger.setAttribute('aria-invalid', 'true');
      open();
    });
    input.addEventListener('click', (e) => e.preventDefault());
    input.form?.addEventListener('reset', () =>
      setTimeout(() => {
        close();
        update();
      }, 0)
    );
    update();
  });
}
