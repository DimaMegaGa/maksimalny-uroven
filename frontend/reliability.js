'use strict';
const pendingRequestKeys = new Map();
let connectionAvailable = true,
  lastConnectedAt = 0;
function connectionState(available) {
  connectionAvailable = available;
  if (available) lastConnectedAt = Date.now();
  const box = document.querySelector('#connection-status');
  if (box?.querySelector) {
    box.hidden = available;
    box.innerHTML = available
      ? ''
      : 'Нет связи с сервером. Текстовые черновики ответов и заданий сохраняются на устройстве. <button type="button" id="retry-connection">Повторить подключение</button>';
    const button = box.querySelector('button');
    if (button) button.onclick = () => refreshFromServer(true);
  }
}
function draftKey(name) {
  return 'maks-draft-v1:' + currentUser()?.id + ':' + name;
}
function readDraft(name) {
  try {
    const item = JSON.parse(localStorage.getItem(draftKey(name)));
    return item && Date.now() - item.savedAt < 7 * 86400000 ? item.values : null;
  } catch {
    return null;
  }
}
function clearDraft(name) {
  try {
    localStorage.removeItem(draftKey(name));
  } catch {}
}
function bindDraft(form, name, allowed) {
  if (!form) return;
  const saved = readDraft(name);
  if (saved)
    for (const [field, value] of Object.entries(saved)) {
      const input = form.elements.namedItem(field);
      if (input && allowed.includes(field)) input.value = value;
    }
  const note = document.createElement('p');
  note.className = 'draft-status';
  note.setAttribute('aria-live', 'polite');
  note.textContent = saved
    ? 'Черновик восстановлен. Фотографии при необходимости прикрепите снова.'
    : 'Текст черновика сохраняется на этом устройстве на 7 дней.';
  form.append(note);
  const save = () => {
    const values = {};
    for (const field of allowed) {
      const input = form.elements.namedItem(field);
      if (input) values[field] = input.value;
    }
    try {
      localStorage.setItem(draftKey(name), JSON.stringify({ savedAt: Date.now(), values }));
      note.textContent = 'Черновик сохранён на этом устройстве';
    } catch {
      note.textContent =
        'Не удалось сохранить черновик на устройстве. Не закрывайте страницу до отправки.';
    }
  };
  form.addEventListener('input', save);
  form.addEventListener('change', save);
  return save;
}
function calendarFile(tasks, label) {
  const escaped = (value) =>
    String(value || '')
      .replace(/\\/g, '\\\\')
      .replace(/\n/g, '\\n')
      .replace(/;/g, '\\;')
      .replace(/,/g, '\\,');
  const fold = (line) => {
    const parts = [];
    let part = '';
    for (const char of line) {
      if (new TextEncoder().encode(part + char).length > 70) {
        parts.push(part);
        part = ' ' + char;
      } else part += char;
    }
    parts.push(part);
    return parts.join('\r\n');
  };
  const stamp = new Date()
    .toISOString()
    .replace(/[-:]/g, '')
    .replace(/\.\d{3}/, '');
  const rows = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//Maksimalny Uroven//Tasks//RU',
    'CALSCALE:GREGORIAN',
    'METHOD:PUBLISH',
    'X-WR-CALNAME:' + escaped(label),
  ];
  for (const task of tasks.filter((t) => !t.archived)) {
    const start = task.deadline.replace(/-/g, '');
    const next = new Date(task.deadline + 'T00:00:00Z');
    next.setUTCDate(next.getUTCDate() + 1);
    rows.push(
      'BEGIN:VEVENT',
      'UID:' + escaped(task.id) + '@maks-level',
      'DTSTAMP:' + stamp,
      'DTSTART;VALUE=DATE:' + start,
      'DTEND;VALUE=DATE:' + next.toISOString().slice(0, 10).replace(/-/g, ''),
      'SUMMARY:' + escaped(task.subject + ': ' + task.title),
      'DESCRIPTION:' + escaped(task.description + '\n' + (task.instructions || '')),
      'END:VEVENT'
    );
  }
  rows.push('END:VCALENDAR');
  return rows.map(fold).join('\r\n') + '\r\n';
}
