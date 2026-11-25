const dryThreshold = 40;
const el = (id) => document.getElementById(id);
const dateTime = new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'medium' });
const clock = new Intl.DateTimeFormat('pt-BR', { timeStyle: 'medium' });
const dayLabel = new Intl.DateTimeFormat('pt-BR', { dateStyle: 'long' });
let chartRows = [];
let source;
let pendingMode;
let historyQuery = new URLSearchParams();
let cursorStack = [null];
let nextCursor;
let historyRequest = 0;

async function api(url, body) {
  const response = await fetch(url, body === undefined ? { cache: 'no-store' } : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.erro || 'Serviço indisponível');
  return payload;
}

function drawChart() {
  const canvas = el('chart');
  const { width, height } = canvas.getBoundingClientRect();
  if (!width || !height) return;
  const ratio = window.devicePixelRatio || 1;
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  const context = canvas.getContext('2d');
  context.scale(ratio, ratio);
  const left = 39, right = width - 10, top = 13, bottom = height - 25;
  const positionY = (value) => bottom - value / 100 * (bottom - top);
  context.font = '11px system-ui';
  context.textBaseline = 'middle';
  context.fillStyle = '#59665d';
  for (const value of [0, 25, 50, 75, 100]) {
    const y = positionY(value);
    context.fillText(value + '%', 0, y);
    context.strokeStyle = '#e6ebe3';
    context.beginPath();
    context.moveTo(left, y);
    context.lineTo(right, y);
    context.stroke();
  }
  if (!chartRows.length) {
    context.fillText('Aguardando leituras', left + 10, positionY(50));
    return;
  }
  const times = chartRows.map((row) => Date.parse(row.instante));
  const lastTime = times.at(-1);
  const firstTime = Math.min(times[0], lastTime - 1000);
  const positionX = (index) => left + (times[index] - firstTime) / (lastTime - firstTime) * (right - left);
  for (const [key, color] of [['luz', '#b47727'], ['umidade', '#45805d']]) {
    context.strokeStyle = context.fillStyle = color;
    context.lineWidth = 2;
    context.beginPath();
    chartRows.forEach((row, index) => {
      const x = positionX(index), y = positionY(row[key]);
      if (index === 0) context.moveTo(x, y);
      else context.lineTo(x, y);
    });
    context.stroke();
    context.beginPath();
    context.arc(positionX(chartRows.length - 1), positionY(chartRows.at(-1)[key]), 3, 0, 2 * Math.PI);
    context.fill();
  }
  context.fillStyle = '#59665d';
  context.fillText(clock.format(firstTime), left, height - 8);
  context.textAlign = 'right';
  context.fillText(clock.format(lastTime), right, height - 8);
}

function renderStatus(status) {
  source = status.fonte;
  const { leitura: row, online } = status;
  el('simulator').hidden = source !== 'simulacao';
  el('connection').dataset.online = online;
  el('connection').textContent = !online ? 'Sem conexão' : source === 'simulacao' ? 'Modo simulação' : 'Arduino conectado';
  el('side-status').textContent = !online ? 'Sem conexão' : source === 'simulacao' ? 'Sensores simulados' : 'Conexão serial ativa';
  el('auto').disabled = el('pause').disabled = !online;
  const current = online ? row : null;
  el('moisture').textContent = current ? current.umidade + '%' : '—';
  el('light').textContent = current ? current.luz + '%' : '—';
  el('pump').textContent = current ? (current.bomba ? 'Ligada' : 'Desligada') : '—';
  el('mode').textContent = current ? (current.modo === 'AUTO' ? 'Automático' : 'Pausado') : 'Sem leitura atual';
  el('moisture-bar').style.width = (current?.umidade ?? 0) + '%';
  el('light-bar').style.width = (current?.luz ?? 0) + '%';
  el('soil-condition').textContent = current ? (current.umidade < dryThreshold ? 'Solo seco' : 'Solo com umidade') : 'Aguardando leitura';
  if (row) el('last-reading').textContent = 'Última leitura às ' + clock.format(new Date(row.instante));
  if (pendingMode && current?.id > pendingMode.after && current.modo === pendingMode.value) {
    el('control-message').textContent = 'Modo confirmado na leitura.';
    pendingMode = null;
  } else if (pendingMode && Date.now() > pendingMode.expires) {
    el('control-message').textContent = 'O dispositivo ainda não confirmou o modo.';
    pendingMode = null;
  }
}

async function refresh() {
  let status;
  try {
    status = await api('/api/status');
    renderStatus(status);
    if (!el('visao').hidden && status.leitura && chartRows.at(-1)?.id !== status.leitura.id) {
      const data = await api('/api/leituras?limite=40');
      chartRows = data.leituras.reverse();
      drawChart();
    }
  } catch {
    if (!status) renderStatus({ fonte: source, online: false });
  } finally {
    setTimeout(refresh, 1000);
  }
}

async function sendMode(value) {
  const message = el('control-message');
  try {
    const result = await api('/api/modo', { modo: value });
    pendingMode = { value, after: result.ultima_leitura, expires: Date.now() + 5000 };
    message.textContent = 'Aguardando confirmação…';
  } catch (error) {
    pendingMode = null;
    message.textContent = error.message;
  }
}

function calendarDate(value, offset = 0) {
  const [year, month, day] = value.split('-').map(Number);
  return new Date(year, month - 1, day + offset);
}

async function loadHistory() {
  const request = ++historyRequest;
  const query = new URLSearchParams(historyQuery);
  if (cursorStack.at(-1)) query.set('cursor', cursorStack.at(-1));
  const message = el('history-message');
  el('previous').disabled = el('next').disabled = true;
  el('rows').replaceChildren();
  message.textContent = 'Consultando…';
  try {
    const data = await api('/api/leituras?' + query);
    if (request !== historyRequest) return;
    nextCursor = data.proximo;
    for (const row of data.leituras) {
      const tr = el('rows').insertRow();
      const values = [dateTime.format(new Date(row.instante)), row.umidade + '%', row.luz + '%',
        row.bomba ? 'Ligada' : 'Desligada', row.modo === 'AUTO' ? 'Automático' : 'Pausado'];
      for (const value of values) tr.insertCell().textContent = value;
    }
    message.textContent = data.leituras.length ? 'Página ' + cursorStack.length : 'Nenhuma leitura para estes filtros.';
  } catch (error) {
    if (request !== historyRequest) return;
    nextCursor = null;
    message.textContent = error.message;
  }
  el('previous').disabled = cursorStack.length === 1;
  el('next').disabled = !nextCursor;
}

el('filters').addEventListener('submit', (event) => {
  event.preventDefault();
  const params = new FormData(event.currentTarget);
  const start = params.get('inicio'), end = params.get('fim');
  if (start && end && start > end) {
    ++historyRequest;
    el('rows').replaceChildren();
    el('previous').disabled = el('next').disabled = true;
    el('history-message').textContent = 'A data final deve ser igual ou posterior à inicial.';
    return;
  }
  historyQuery = new URLSearchParams();
  if (start) historyQuery.set('inicio', calendarDate(start).toISOString());
  if (end) historyQuery.set('fim', calendarDate(end, 1).toISOString());
  if (params.get('solo') === 'seco') historyQuery.set('umidade_max', dryThreshold - 1);
  if (params.get('solo') === 'umido') historyQuery.set('umidade_min', dryThreshold);
  for (const key of ['luz_min', 'bomba']) {
    if (params.get(key) !== '') historyQuery.set(key, params.get(key));
  }
  cursorStack = [null];
  loadHistory();
});

el('yesterday').addEventListener('click', () => {
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  const date = [yesterday.getFullYear(), yesterday.getMonth() + 1, yesterday.getDate()]
    .map((value) => String(value).padStart(2, '0')).join('-');
  el('filters').elements.inicio.value = el('filters').elements.fim.value = date;
  el('filters').requestSubmit();
});

el('previous').addEventListener('click', () => {
  if (cursorStack.length > 1) {
    cursorStack.pop();
    loadHistory();
  }
});

el('next').addEventListener('click', () => {
  if (nextCursor) {
    cursorStack.push(nextCursor);
    loadHistory();
  }
});

el('simulation-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  try {
    await api('/api/simulacao', { umidade: Number(data.get('umidade')), luz: Number(data.get('luz')) });
    el('simulation-message').textContent = 'Valores aplicados à próxima leitura.';
  } catch (error) {
    el('simulation-message').textContent = error.message;
  }
});

function navigate() {
  const tab = location.hash === '#historico' ? 'historico' : 'visao';
  el('visao').hidden = tab !== 'visao';
  el('historico').hidden = tab !== 'historico';
  document.querySelectorAll('nav a').forEach((link) => {
    const active = link.hash === '#' + tab;
    link.classList.toggle('active', active);
    if (active) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
  if (tab === 'historico') loadHistory();
  else drawChart();
}

el('auto').addEventListener('click', () => sendMode('AUTO'));
el('pause').addEventListener('click', () => sendMode('PAUSE'));
el('today').textContent = dayLabel.format(new Date());
window.addEventListener('hashchange', navigate);
new ResizeObserver(drawChart).observe(el('chart'));
navigate();
refresh();
