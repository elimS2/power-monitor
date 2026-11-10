/* Power Monitor dashboard */
(function() {
  'use strict';

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js');
  }

  // Favicon from body data
  function initFavicon() {
    var down = document.body.getAttribute('data-pm-down') === '1';
    var icon = down ? 'icon_off.png' : 'icon_on.png';
    var old = document.querySelector('link[rel="icon"]');
    if (old) old.remove();
    var link = document.createElement('link');
    link.rel = 'icon';
    link.type = 'image/png';
    link.href = '/icons/' + icon + '?t=' + Date.now();
    document.head.appendChild(link);
  }
  initFavicon();

  // Clocks
  function updClocks() {
    var now = new Date();
    var fmt = function(tz) {
      return now.toLocaleTimeString('uk-UA', { timeZone: tz, hour: '2-digit', minute: '2-digit', second: '2-digit' });
    };
    var el = document.getElementById('clocks');
    if (el) el.innerHTML =
      '<span>Київ ' + fmt('Europe/Kyiv') + '</span>' +
      '<span>UTC ' + fmt('UTC') + '</span>' +
      '<span>New York ' + fmt('America/New_York') + '</span>';
  }
  updClocks();
  setInterval(updClocks, 1000);

  // Schedule "now" indicator — move every 30 min (server renders once, we keep it current)
  function updScheduleNow() {
    var board = document.getElementById('pm-sched-board');
    if (board) {
      if (typeof window.pmPaintBoardNow === 'function') window.pmPaintBoardNow();
      return;
    }
    var now = new Date();
    var fmt = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Kyiv', hour: 'numeric', minute: 'numeric', hour12: false });
    var parts = fmt.formatToParts(now);
    var hour = parseInt(parts.find(function(p) { return p.type === 'hour'; }).value, 10);
    var minute = parseInt(parts.find(function(p) { return p.type === 'minute'; }).value, 10);
    var slot = hour * 2 + (minute >= 30 ? 1 : 0);
    var isDown = document.body.getAttribute('data-pm-down') === '1';

    document.querySelectorAll('.sg-table .sg-now').forEach(function(td) {
      td.classList.remove('sg-now', 'sg-now-on', 'sg-now-off');
    });

    var desktop = document.querySelector('.sg-wrap.sg-desktop .sg-table');
    if (desktop) {
      var rows = desktop.querySelectorAll('tr');
      if (rows[1]) {
        var cells = rows[1].querySelectorAll('td');
        if (cells[slot + 1]) {
          cells[slot + 1].classList.add('sg-now', isDown ? 'sg-now-off' : 'sg-now-on');
        }
      }
    }

    var mobile = document.querySelector('.sg-mobile');
    if (mobile) {
      var tables = mobile.querySelectorAll('table.sg-table');
      if (tables[0]) {
        var mRows = tables[0].querySelectorAll('tr');
        var targetRow = slot < 24 ? mRows[1] : mRows[3];
        var cellIdx = slot < 24 ? slot : slot - 24;
        if (targetRow && targetRow.cells[cellIdx]) {
          targetRow.cells[cellIdx].classList.add('sg-now', isDown ? 'sg-now-off' : 'sg-now-on');
        }
      }
    }
  }
  updScheduleNow();
  setInterval(updScheduleNow, 10000);

  var schedDetails = document.getElementById('sched_details');
  if (schedDetails) schedDetails.addEventListener('toggle', updScheduleNow);

  // Details localStorage persistence
  document.querySelectorAll('details[data-ls-key]').forEach(function(d) {
    var key = d.getAttribute('data-ls-key');
    var defaultOpen = d.getAttribute('data-default-open') === '1';
    var saved = localStorage.getItem(key);
    if (saved !== null) d.open = (saved === '1'); else d.open = defaultOpen;
    d.addEventListener('toggle', function() { localStorage.setItem(key, d.open ? '1' : '0'); });
  });

  // Drag-drop section reorder
  var ORDER_KEY = 'pm_section_order';
  var ORDER_REV_KEY = 'pm_section_order_rev';
  var ORDER_REV = '2026-11-10-top4';
  var ORDER_PREFIX = ['breaker_details', 'voltage_details', 'sched_details', 'collections_details'];
  var container = document.getElementById('dashboard-sections');
  if (container) {
    var order = JSON.parse(localStorage.getItem(ORDER_KEY) || 'null');
    if (localStorage.getItem(ORDER_REV_KEY) !== ORDER_REV) {
      var domIds = Array.from(container.querySelectorAll('.dashboard-section')).map(function(s) {
        return s.dataset.sectionId;
      });
      var base = (order && order.length) ? order.slice() : domIds.slice();
      domIds.forEach(function(id) {
        if (base.indexOf(id) < 0) base.push(id);
      });
      var rest = base.filter(function(id) { return ORDER_PREFIX.indexOf(id) < 0; });
      order = ORDER_PREFIX.filter(function(id) { return domIds.indexOf(id) >= 0; }).concat(rest);
      localStorage.setItem(ORDER_KEY, JSON.stringify(order));
      localStorage.setItem(ORDER_REV_KEY, ORDER_REV);
    }
    if (order) {
      var byId = {};
      container.querySelectorAll('.dashboard-section').forEach(function(s) {
        byId[s.dataset.sectionId] = s;
      });
      order.forEach(function(id) {
        var el = byId[id];
        if (el) container.appendChild(el);
      });
      container.querySelectorAll('.dashboard-section').forEach(function(s) {
        if (order.indexOf(s.dataset.sectionId) < 0) container.appendChild(s);
      });
    }
    var handle = null;
    container.addEventListener('dragstart', function(e) {
      if (!e.target.classList.contains('drag-handle')) return;
      handle = e.target.closest('.dashboard-section');
      if (!handle) return;
      e.dataTransfer.setData('text/plain', handle.dataset.sectionId);
      e.dataTransfer.effectAllowed = 'move';
      handle.classList.add('dragging');
    });
    container.addEventListener('dragend', function(e) {
      if (handle) { handle.classList.remove('dragging'); handle = null; }
      container.querySelectorAll('.dashboard-section').forEach(function(s) { s.classList.remove('drag-over'); });
    });
    container.addEventListener('dragover', function(e) {
      e.preventDefault();
      container.querySelectorAll('.dashboard-section').forEach(function(s) { s.classList.remove('drag-over'); });
      var t = e.target.closest('.dashboard-section');
      if (t && t !== handle) { t.classList.add('drag-over'); e.dataTransfer.dropEffect = 'move'; }
    });
    container.addEventListener('dragleave', function(e) {
      var t = e.target.closest('.dashboard-section');
      if (t) t.classList.remove('drag-over');
    });
    container.addEventListener('drop', function(e) {
      e.preventDefault();
      var t = e.target.closest('.dashboard-section');
      if (!t || t === handle) return;
      t.classList.remove('drag-over');
      var id = e.dataTransfer.getData('text/plain');
      var dragged = container.querySelector('[data-section-id="' + id + '"]');
      if (dragged && dragged !== t) {
        var all = Array.from(container.querySelectorAll('.dashboard-section'));
        var idx = all.indexOf(t);
        if (idx >= 0) container.insertBefore(dragged, all[idx]);
        else container.appendChild(dragged);
        var newOrder = Array.from(container.querySelectorAll('.dashboard-section')).map(function(s) { return s.dataset.sectionId; });
        localStorage.setItem(ORDER_KEY, JSON.stringify(newOrder));
      }
    });
  }

  var key = document.body.getAttribute('data-pm-key') || '';

  var schedBoard = document.getElementById('pm-sched-board');
  if (schedBoard && key) {
    var ourQueue = schedBoard.getAttribute('data-our-queue') || '';
    var boardPayload = null;
    var selectedDate = '';
    var WEEKDAYS = ['Понеділок', 'Вівторок', 'Середа', 'Четвер', "П'ятниця", 'Субота', 'Неділя'];
    var KIND = { added: 'додано', removed: 'скасовано', moved: 'перенесено', severity: 'змінено' };
    var STATUS = { ok: 'світло', off: 'відключення', maybe: 'можливе' };
    var LAYER_KEYS = [
      ['pm_sched_show_off', 'Відключення', '1'],
      ['pm_sched_show_changed', 'Змінені', '1'],
      ['pm_sched_show_cancelled', 'Скасовані', '1'],
      ['pm_sched_show_actual', 'Наші фактичні', '1'],
      ['pm_sched_show_voltage', 'Проблеми напруги', '0']
    ];

    function layerOn(storageKey, fallback) {
      var saved = localStorage.getItem(storageKey);
      return (saved === null ? fallback : saved) === '1';
    }
    function extraGroups() {
      try { return JSON.parse(localStorage.getItem('pm_sched_groups') || '[]'); }
      catch (e) { return []; }
    }
    function groupVisible(queue) {
      if (queue === ourQueue) return true;
      return extraGroups().indexOf(queue) >= 0;
    }
    function kyivToday() {
      return new Intl.DateTimeFormat('en-CA', {
        timeZone: 'Europe/Kyiv', year: 'numeric', month: '2-digit', day: '2-digit'
      }).format(new Date());
    }
    function prettyDate(iso) {
      var parts = iso.split('-');
      return parts[2] + '.' + parts[1] + '.' + parts[0];
    }
    function statusName(code) {
      return STATUS[code] || code || '';
    }
    function weekdayName(iso) {
      var parts = iso.split('-');
      var utc = new Date(Date.UTC(+parts[0], +parts[1] - 1, +parts[2]));
      var day = utc.getUTCDay();
      return WEEKDAYS[day === 0 ? 6 : day - 1];
    }
    function slotClock(index) {
      var total = index * 30;
      var h = Math.floor(total / 60);
      var m = total % 60;
      if (h >= 24) return '24:00';
      return (h < 10 ? '0' : '') + h + ':' + (m < 10 ? '0' : '') + m;
    }
    function kyivMidnightMs(iso) {
      var parts = iso.split('-');
      var utcMidnight = Date.UTC(+parts[0], +parts[1] - 1, +parts[2], 0, 0, 0);
      var fmt = new Intl.DateTimeFormat('en-US', {
        timeZone: 'Europe/Kyiv', hour12: false,
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit'
      });
      var guess = new Date(utcMidnight);
      var map = {};
      fmt.formatToParts(guess).forEach(function(p) { map[p.type] = p.value; });
      var hour = map.hour === '24' ? 0 : +map.hour;
      var asUtc = Date.UTC(+map.year, +map.month - 1, +map.day, hour, +map.minute, +map.second);
      return utcMidnight - (asUtc - guess.getTime());
    }
    function fmtKyiv(ts) {
      var text = new Intl.DateTimeFormat('uk-UA', {
        timeZone: 'Europe/Kyiv', hourCycle: 'h23',
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit'
      }).format(new Date(ts * 1000));
      return text.replace(',', '');
    }
    function kyivClock() {
      var fmt = new Intl.DateTimeFormat('en-CA', {
        timeZone: 'Europe/Kyiv', hour: 'numeric', minute: 'numeric', second: 'numeric', hour12: false
      });
      var map = {};
      fmt.formatToParts(new Date()).forEach(function(p) { map[p.type] = p.value; });
      var hour = parseInt(map.hour, 10);
      if (hour === 24) hour = 0;
      var minute = parseInt(map.minute, 10);
      var second = parseInt(map.second, 10) || 0;
      return { hour: hour, minute: minute, second: second, slot: hour * 2 + (minute >= 30 ? 1 : 0) };
    }
    function currentSlot() {
      return kyivClock().slot;
    }

    function loadBoard(date) {
      var url = '/api/schedule-board?key=' + encodeURIComponent(key);
      if (date) url += '&date=' + encodeURIComponent(date);
      fetch(url, { cache: 'no-store' }).then(function(r) { return r.ok ? r.json() : null; }).then(function(data) {
        if (!data) return;
        boardPayload = data;
        selectedDate = data.date;
        renderBoard();
      }).catch(function() {});
    }

    function renderBoard() {
      var data = boardPayload;
      if (!data) return;
      var dates = data.available_dates || [];
      var index = dates.indexOf(data.date);
      var showOff = layerOn('pm_sched_show_off', '1');
      var showChanged = layerOn('pm_sched_show_changed', '1');
      var showCancelled = layerOn('pm_sched_show_cancelled', '1');
      var showActual = layerOn('pm_sched_show_actual', '1');
      var showVoltage = layerOn('pm_sched_show_voltage', '0');
      var html = '';
      html += '<div class="sb-controls"><button type="button" id="sb-prev"' + (index <= 0 ? ' disabled' : '') + '>‹</button>';
      html += '<span class="sb-date" id="sb-date">' + prettyDate(data.date) + ' (' + weekdayName(data.date) + ')</span>';
      html += '<button type="button" id="sb-next"' + (index < 0 || index >= dates.length - 1 ? ' disabled' : '') + '>›</button></div>';
      html += '<div class="sb-checks" id="sb-groups">';
      Object.keys(data.groups || {}).sort().forEach(function(queue) {
        var ours = queue === ourQueue;
        var on = groupVisible(queue);
        html += '<label class="' + (ours ? 'sb-ours' : '') + '"><input type="checkbox" data-sb-group="' + queue + '"' +
          (on ? ' checked' : '') + (ours ? ' disabled' : '') + '> ' + queue + (ours ? ' наша' : '') + '</label>';
      });
      html += '</div><div class="sb-checks" id="sb-layers">';
      LAYER_KEYS.forEach(function(item) {
        var on = layerOn(item[0], item[2]);
        html += '<label><input type="checkbox" data-sb-layer="' + item[0] + '"' + (on ? ' checked' : '') + '> ' + item[1] + '</label>';
      });
      html += '</div>';
      if (data.emergency) {
        html += '<div class="sb-banner">Екстрені відключення: опублікований графік не діє</div>';
      }
      if (data.date === kyivToday()) {
        html += '<div class="sb-note">Жовте блимання — графік і світло сходяться. Червоне — ні.</div>';
      }
      if (showActual && data.overlay_ready) {
        html += '<div class="sb-note">Зелена смуга — світло було. Червона — не було.</div>';
      }
      if (!data.overlay_ready) {
        html += '<div class="sb-note">Фактичні ще не зведені</div>';
      }
      html += '<div class="sb-wrap"><table class="sb-table"><colgroup><col class="sb-col-label"><col span="48"></colgroup><tr><th class="sb-label"></th>';
      for (var h = 0; h < 24; h++) html += '<th colspan="2" data-sb-hour="' + h + '">' + (h < 10 ? '0' : '') + h + '</th>';
      html += '</tr>';
      Object.keys(data.groups || {}).sort().forEach(function(queue) {
        if (!groupVisible(queue)) return;
        var group = data.groups[queue];
        html += '<tr class="' + (queue === ourQueue ? 'sb-ours' : '') + '" data-sb-queue="' + queue + '"><td class="sb-label">' + queue + '</td>';
        if (!group.has_snapshot) {
          html += '<td class="sb-empty" colspan="48">Немає знімка</td></tr>';
          return;
        }
        var changed = (data.changed_slots && data.changed_slots[queue]) || [];
        var cancelled = (data.cancelled_slots && data.cancelled_slots[queue]) || [];
        for (var i = 0; i < 48; i++) {
          var status = group.grid[i] || 'ok';
          var cls = 'sb-cell';
          if (showOff) cls += ' sg-' + status;
          if (showChanged && changed.indexOf(i) >= 0) cls += ' sb-changed';
          if (showCancelled && cancelled.indexOf(i) >= 0) cls += ' sb-cancelled';
          html += '<td class="' + cls + '" data-sb-slot="' + i + '" data-sb-plan="' + status + '"></td>';
        }
        html += '</tr>';
      });
      if (showActual && data.overlay_ready) html += factLane(data.actual, data.date);
      if (showVoltage) {
        var highs = (data.voltage || []).filter(function(item) { return item.band === 'high'; });
        var lows = (data.voltage || []).filter(function(item) { return item.band === 'low'; });
        html += laneRow(highs, 'sb-bar-high', data.date);
        html += laneRow(lows, 'sb-bar-low', data.date);
      }
      html += '</table><div class="sb-now-line" hidden></div></div>';
      if (data.match) {
        html += '<div class="sb-match">Збіглось ' + data.match.hit_min + ' хв · Світло було всупереч графіку ' +
          data.match.miss_min + ' хв · Позапланово не було ' + data.match.unplanned_min + ' хв</div>';
      }
      html += '<div class="sb-caption">За різницею знімків, не окреме поле ДТЕК</div>';
      var visibleChanges = (data.changes || []).filter(function(row) { return groupVisible(row.queue); });
      if (!visibleChanges.length) {
        html += '<div class="sb-note">Змін ще не було</div>';
      } else {
        var changesOpen = localStorage.getItem('pm_sched_changes_open') === '1';
        html += '<details class="sb-changes-details"' + (changesOpen ? ' open' : '') + '><summary>Зміни графіка (' + visibleChanges.length + ')</summary>';
        html += '<table class="sb-changes"><tr><th>Коли побачили</th><th>Група</th><th>Що сталося</th><th>Було</th><th>Стало</th></tr>';
        visibleChanges.forEach(function(row) {
          var was = slotClock(row.start_slot) + '–' + slotClock(row.end_slot) + ' ' + statusName(row.from_status);
          var became = row.kind === 'moved'
            ? slotClock(row.peer_start_slot) + '–' + slotClock(row.peer_end_slot) + ' ' + statusName(row.to_status)
            : slotClock(row.start_slot) + '–' + slotClock(row.end_slot) + ' ' + statusName(row.to_status);
          var name = row.queue === ourQueue ? '<strong>' + row.queue + '</strong>' : row.queue;
          html += '<tr><td>' + fmtKyiv(row.fetched_at) + '</td><td>' + name + '</td><td>' +
            (KIND[row.kind] || row.kind) + '</td><td>' + was + '</td><td>' + became + '</td></tr>';
        });
        html += '</table></details>';
      }
      schedBoard.innerHTML = html;
      var changesDetails = schedBoard.querySelector('.sb-changes-details');
      if (changesDetails) {
        changesDetails.addEventListener('toggle', function() {
          localStorage.setItem('pm_sched_changes_open', changesDetails.open ? '1' : '0');
        });
      }
      var prev = document.getElementById('sb-prev');
      var next = document.getElementById('sb-next');
      if (prev) prev.addEventListener('click', function() {
        if (index > 0) loadBoard(dates[index - 1]);
      });
      if (next) next.addEventListener('click', function() {
        if (index >= 0 && index < dates.length - 1) loadBoard(dates[index + 1]);
      });
      schedBoard.querySelectorAll('[data-sb-group]').forEach(function(input) {
        input.addEventListener('change', function() {
          var queue = input.getAttribute('data-sb-group');
          var list = extraGroups().filter(function(item) { return item !== queue; });
          if (input.checked) list.push(queue);
          localStorage.setItem('pm_sched_groups', JSON.stringify(list));
          renderBoard();
        });
      });
      schedBoard.querySelectorAll('[data-sb-layer]').forEach(function(input) {
        input.addEventListener('change', function() {
          localStorage.setItem(input.getAttribute('data-sb-layer'), input.checked ? '1' : '0');
          renderBoard();
        });
      });
      if (typeof window.pmPaintBoardNow === 'function') window.pmPaintBoardNow();
    }

    function laneBars(items, className, iso) {
      if (!items || !items.length) return '';
      var startMs = kyivMidnightMs(iso);
      var span = 86400000;
      var bars = '';
      items.forEach(function(item) {
        var left = ((item.start * 1000) - startMs) / span * 100;
        var width = ((item.end - item.start) * 1000) / span * 100;
        if (left < 0) { width += left; left = 0; }
        if (left >= 100 || width <= 0) return;
        if (left + width > 100) width = 100 - left;
        bars += '<div class="sb-bar ' + className + '" style="left:' + left.toFixed(3) + '%;width:' + width.toFixed(3) + '%"></div>';
      });
      return bars;
    }

    function laneRow(items, className, iso) {
      var bars = laneBars(items, className, iso);
      if (!bars) return '';
      return '<tr class="sb-lane-row"><td class="sb-label"></td><td class="sb-lane-cell" colspan="48">' + bars + '</td></tr>';
    }

    function factOnSegments(actual, iso) {
      var startMs = kyivMidnightMs(iso);
      var endMs = startMs + 86400000;
      if (iso === kyivToday()) endMs = Math.min(Date.now(), endMs);
      var spans = (actual || []).map(function(item) {
        return {
          start: Math.max(item.start * 1000, startMs),
          end: Math.min(item.end * 1000, endMs)
        };
      }).filter(function(item) { return item.end > item.start; });
      spans.sort(function(a, b) { return a.start - b.start; });
      var merged = [];
      spans.forEach(function(item) {
        var last = merged[merged.length - 1];
        if (last && item.start <= last.end) last.end = Math.max(last.end, item.end);
        else merged.push({ start: item.start, end: item.end });
      });
      var green = [];
      var cursor = startMs;
      merged.forEach(function(item) {
        if (item.start > cursor) green.push({ start: cursor / 1000, end: item.start / 1000 });
        cursor = Math.max(cursor, item.end);
      });
      if (endMs - cursor > 1000) green.push({ start: cursor / 1000, end: endMs / 1000 });
      return green;
    }

    function factLane(actual, iso) {
      var bars = laneBars(factOnSegments(actual, iso), 'sb-bar-on', iso) + laneBars(actual, 'sb-bar-actual', iso);
      if (!bars) return '';
      return '<tr class="sb-lane-row"><td class="sb-label"></td><td class="sb-lane-cell" colspan="48">' + bars + '</td></tr>';
    }

    function boardNowClass(cell) {
      var down = document.body.getAttribute('data-pm-down') === '1';
      var planned = cell.getAttribute('data-sb-plan') || 'ok';
      var outage = planned === 'off' || planned === 'maybe';
      var miss = (outage && !down) || (planned === 'ok' && down);
      return miss ? 'sb-now-no' : 'sb-now-yes';
    }

    function placeNowLine() {
      var line = schedBoard.querySelector('.sb-now-line');
      var table = schedBoard.querySelector('.sb-table');
      var label = table && table.querySelector('th.sb-label');
      if (!line || !table || !label) return;
      var today = boardPayload && boardPayload.date === kyivToday();
      schedBoard.querySelectorAll('[data-sb-hour]').forEach(function(th) {
        th.classList.remove('sb-now-hour');
      });
      if (!today) {
        line.hidden = true;
        return;
      }
      var clock = kyivClock();
      var head = schedBoard.querySelector('[data-sb-hour="' + clock.hour + '"]');
      if (head) head.classList.add('sb-now-hour');
      var startMs = kyivMidnightMs(boardPayload.date);
      var frac = (Date.now() - startMs) / 86400000;
      if (frac < 0) frac = 0;
      if (frac > 1) frac = 1;
      var labelW = label.offsetWidth;
      var x = labelW + (table.offsetWidth - labelW) * frac;
      line.hidden = false;
      line.style.left = x.toFixed(2) + 'px';
    }

    window.pmPaintBoardNow = function() {
      if (!schedBoard || !boardPayload) return;
      var today = boardPayload.date === kyivToday();
      schedBoard.querySelectorAll('[data-sb-slot]').forEach(function(cell) {
        cell.classList.remove('sb-now', 'sb-now-yes', 'sb-now-no');
      });
      placeNowLine();
      if (!today) return;
      var row = schedBoard.querySelector('tr[data-sb-queue="' + ourQueue + '"]');
      if (!row) return;
      var cell = row.querySelector('[data-sb-slot="' + currentSlot() + '"]');
      if (cell) cell.classList.add(boardNowClass(cell));
    };

    loadBoard('');
    setInterval(function() {
      if (selectedDate && selectedDate === kyivToday()) loadBoard(selectedDate);
    }, 60000);
    document.addEventListener('visibilitychange', function() {
      if (document.visibilityState === 'visible') loadBoard(selectedDate);
    });
    window.addEventListener('resize', function() {
      if (typeof window.pmPaintBoardNow === 'function') window.pmPaintBoardNow();
    });
  }

  // Admin keys (only for admin)
  var adminKeysContainer = document.getElementById('admin-keys-container');
  if (adminKeysContainer && key) {
    fetch('/api/admin/keys?key=' + encodeURIComponent(key), { cache: 'no-store' })
      .then(function(r) {
        if (!r.ok) { adminKeysContainer.innerHTML = ''; adminKeysContainer.closest('.dashboard-section') && adminKeysContainer.closest('.dashboard-section').remove(); return; }
        return r.json();
      })
      .then(function(keys) {
        if (!keys || !keys.length) return;
        var html = '<table><tr><th>Ключ</th><th>Стан</th><th>Дії</th></tr>';
        keys.forEach(function(k) {
          var status = k.enabled ? '\u2705 Увімкнено' : '\u274c Вимкнено';
          var btn = k.label === 'admin' ? '—' : '<button type="button" class="admin-key-toggle btn" data-label="' + k.label + '" data-enabled="' + k.enabled + '">' + (k.enabled ? 'Вимкнути' : 'Увімкнути') + '</button>';
          var openUrl = '/api/admin/keys/' + encodeURIComponent(k.label) + '/open-dashboard?key=' + encodeURIComponent(key);
          html += '<tr><td>' + k.label + ' <small>(<a href="' + openUrl + '" target="_blank" rel="noopener" style="color:#6ee7b7">' + k.key_preview + '</a>)</small></td><td>' + status + '</td><td>' + btn + '</td></tr>';
        });
        html += '</table>';
        adminKeysContainer.innerHTML = html;
        adminKeysContainer.querySelectorAll('.admin-key-toggle').forEach(function(btn) {
          btn.addEventListener('click', function() {
            var label = btn.dataset.label;
            var enabled = btn.dataset.enabled !== 'true';
            fetch('/api/admin/keys/' + encodeURIComponent(label) + '/enabled?key=' + encodeURIComponent(key) + '&enabled=' + enabled, { method: 'POST' })
              .then(function(r) { return r.json(); })
              .then(function() {
                btn.dataset.enabled = enabled;
                btn.textContent = enabled ? 'Вимкнути' : 'Увімкнути';
                var statusTd = btn.closest('tr').querySelector('td:nth-child(2)');
                if (statusTd) statusTd.textContent = enabled ? '\u2705 Увімкнено' : '\u274c Вимкнено';
              });
          });
        });
      });
  }

  // Voltage chart: wheel zoom and drag, kept across the 10s refresh.
  var vZoom = null;
  var vDrag = null;
  var vShift = 0;
  var vchartReload = function() {};
  try {
    vShift = Math.max(0, parseInt(sessionStorage.getItem('pm_vchart_shift') || '0', 10) || 0);
  } catch (err) {
    vShift = 0;
  }

  function vchartMeta(main) {
    return {
      t0: +main.getAttribute('data-t0'),
      t1: +main.getAttribute('data-t1'),
      y0: +main.getAttribute('data-ymin'),
      y1: +main.getAttribute('data-ymax'),
      w: +main.getAttribute('data-w'),
      plotH: +main.getAttribute('data-ploth'),
      stripH: +main.getAttribute('data-striph')
    };
  }

  function vchartFull(meta) {
    return { t0: meta.t0, t1: meta.t1, y0: meta.y0, y1: meta.y1 };
  }

  function vchartClamp(z, meta) {
    var minT = 10 * 60;
    var minY = 4;
    var tSpan = Math.max(minT, Math.min(meta.t1 - meta.t0, z.t1 - z.t0));
    var ySpan = Math.max(minY, Math.min(meta.y1 - meta.y0, z.y1 - z.y0));
    var t0 = (z.t0 + z.t1) / 2 - tSpan / 2;
    var t1 = t0 + tSpan;
    var y0 = (z.y0 + z.y1) / 2 - ySpan / 2;
    var y1 = y0 + ySpan;
    if (t0 < meta.t0) { t1 += meta.t0 - t0; t0 = meta.t0; }
    if (t1 > meta.t1) { t0 -= t1 - meta.t1; t1 = meta.t1; }
    t0 = Math.max(meta.t0, t0);
    t1 = Math.min(meta.t1, t0 + tSpan);
    if (y0 < meta.y0) { y1 += meta.y0 - y0; y0 = meta.y0; }
    if (y1 > meta.y1) { y0 -= y1 - meta.y1; y1 = meta.y1; }
    y0 = Math.max(meta.y0, y0);
    y1 = Math.min(meta.y1, y0 + ySpan);
    return { t0: t0, t1: t1, y0: y0, y1: y1 };
  }

  function vchartIsFull(z, meta) {
    return (z.t1 - z.t0) > (meta.t1 - meta.t0) - 1
      && (z.y1 - z.y0) > (meta.y1 - meta.y0) - 0.05;
  }

  function vchartPoint(svg, clientX, clientY) {
    if (!svg.createSVGPoint) return null;
    var pt = svg.createSVGPoint();
    pt.x = clientX;
    pt.y = clientY;
    var ctm = svg.getScreenCTM();
    if (!ctm) return null;
    return pt.matrixTransform(ctm.inverse());
  }

  function vchartTzOffset(ts) {
    var date = new Date(ts * 1000);
    var local = new Date(date.toLocaleString('en-US', { timeZone: 'Europe/Kyiv' }));
    var utc = new Date(date.toLocaleString('en-US', { timeZone: 'UTC' }));
    return (local.getTime() - utc.getTime()) / 1000;
  }

  function vchartTimeLabel(ts) {
    var date = new Date(ts * 1000);
    var hour = new Intl.DateTimeFormat('en-GB', {
      timeZone: 'Europe/Kyiv', hour: '2-digit', hourCycle: 'h23'
    }).format(date);
    if (hour === '00') {
      return new Intl.DateTimeFormat('uk-UA', {
        timeZone: 'Europe/Kyiv', day: '2-digit', month: '2-digit'
      }).format(date);
    }
    return new Intl.DateTimeFormat('uk-UA', {
      timeZone: 'Europe/Kyiv', hour: '2-digit', minute: '2-digit'
    }).format(date);
  }

  function vchartLayout(meta, z) {
    var yAxis = document.querySelector('#pm-voltage .vchart-yaxis');
    var xAxis = document.querySelector('#pm-voltage .vchart-xaxis');
    var nowEl = document.querySelector('#pm-voltage .vchart-now');
    var yStep = 20;
    var ySteps = [1, 2, 5, 10, 20];
    var yTarget = (z.y1 - z.y0) / 4;
    for (var i = 0; i < ySteps.length; i++) if (ySteps[i] >= yTarget) { yStep = ySteps[i]; break; }
    if (yAxis) {
      var yHtml = '';
      var v = Math.ceil(z.y0 / yStep) * yStep;
      while (v <= z.y1 + 0.01) {
        var top = (z.y1 - v) / (z.y1 - z.y0) * 100;
        if (top < 4) top = 4;
        if (top > 96) top = 96;
        yHtml += '<span style="top:' + top.toFixed(2) + '%">' + v + '</span>';
        v += yStep;
      }
      yAxis.innerHTML = yHtml;
    }
    if (xAxis) {
      var tSteps = [5 * 60, 10 * 60, 15 * 60, 30 * 60, 3600, 2 * 3600, 3 * 3600, 6 * 3600];
      var tStep = 3 * 3600;
      var tTarget = (z.t1 - z.t0) / 5;
      for (var j = 0; j < tSteps.length; j++) if (tSteps[j] >= tTarget) { tStep = tSteps[j]; break; }
      var off = vchartTzOffset((z.t0 + z.t1) / 2);
      var ts = Math.ceil((z.t0 + off) / tStep) * tStep - off;
      var xHtml = '';
      while (ts < z.t1) {
        var left = (ts - z.t0) / (z.t1 - z.t0) * 100;
        if (left > 2 && left < 98) xHtml += '<span style="left:' + left.toFixed(2) + '%">' + vchartTimeLabel(ts) + '</span>';
        ts += tStep;
      }
      xAxis.innerHTML = xHtml;
    }
    if (nowEl) {
      var now = Date.now() / 1000;
      if (now < z.t0 || now > z.t1) nowEl.hidden = true;
      else {
        nowEl.hidden = false;
        nowEl.style.left = ((now - z.t0) / (z.t1 - z.t0) * 100).toFixed(2) + '%';
      }
    }
  }

  function vchartApply() {
    var main = document.querySelector('#pm-voltage .vchart-main');
    var strip = document.querySelector('#pm-voltage .vchart-strip');
    if (!main || !strip) return;
    var meta = vchartMeta(main);
    if (vZoom) {
      vZoom.y0 = meta.y0;
      vZoom.y1 = meta.y1;
    }
    var z = vZoom ? vchartClamp(vZoom, meta) : vchartFull(meta);
    if (vZoom && vchartIsFull(z, meta)) vZoom = null;
    if (!vZoom) z = vchartFull(meta);
    else vZoom = z;
    var x = (z.t0 - meta.t0) / (meta.t1 - meta.t0) * meta.w;
    var w = (z.t1 - z.t0) / (meta.t1 - meta.t0) * meta.w;
    var y = (meta.y1 - z.y1) / (meta.y1 - meta.y0) * meta.plotH;
    var h = (z.y1 - z.y0) / (meta.y1 - meta.y0) * meta.plotH;
    main.setAttribute('viewBox', x.toFixed(2) + ' ' + y.toFixed(2) + ' ' + w.toFixed(2) + ' ' + h.toFixed(2));
    strip.setAttribute('viewBox', x.toFixed(2) + ' 0 ' + w.toFixed(2) + ' ' + meta.stripH);
    vchartLayout(meta, z);
    var btn = document.querySelector('#pm-voltage .vchart-reset');
    if (btn) btn.hidden = !vZoom;
    vchartSyncFullscreen();
  }

  function vchartInFullscreen() {
    var host = document.getElementById('pm-voltage');
    return !!(host && document.fullscreenElement === host);
  }

  function vchartSyncFullscreen() {
    var btn = document.querySelector('#pm-voltage .vchart-full');
    if (!btn) return;
    var on = vchartInFullscreen();
    btn.setAttribute('aria-label', on ? 'Згорнути' : 'На весь екран');
    var enter = btn.querySelector('.vchart-full-enter');
    var exit = btn.querySelector('.vchart-full-exit');
    if (enter) enter.hidden = on;
    if (exit) exit.hidden = !on;
  }

  function vchartToggleFullscreen() {
    var host = document.getElementById('pm-voltage');
    if (!host) return;
    if (vchartInFullscreen()) {
      if (document.exitFullscreen) document.exitFullscreen();
    } else if (host.requestFullscreen) {
      host.requestFullscreen();
    }
  }

  document.addEventListener('fullscreenchange', vchartSyncFullscreen);

  document.addEventListener('wheel', function(e) {
    var host = e.target.closest && e.target.closest('#pm-voltage .vchart-plot, #pm-voltage .vchart-strip');
    if (!host) return;
    var main = document.querySelector('#pm-voltage .vchart-main');
    var svg = e.target.closest('.vchart-main, .vchart-strip');
    if (!main || !svg) return;
    e.preventDefault();
    var meta = vchartMeta(main);
    var z = vZoom || vchartFull(meta);
    var pt = vchartPoint(svg, e.clientX, e.clientY);
    if (!pt) return;
    var dy = e.deltaY;
    if (e.deltaMode === 1) dy *= 16;
    if (e.deltaMode === 2) dy *= 120;
    var factor = Math.exp(dy * 0.0012);
    if (factor < 0.75) factor = 0.75;
    if (factor > 1.35) factor = 1.35;
    var t = meta.t0 + (pt.x / meta.w) * (meta.t1 - meta.t0);
    var next = {
      t0: t - (t - z.t0) * factor,
      t1: t + (z.t1 - t) * factor,
      y0: meta.y0,
      y1: meta.y1
    };
    next = vchartClamp(next, meta);
    vZoom = vchartIsFull(next, meta) ? null : next;
    vchartApply();
  }, { passive: false });

  document.addEventListener('pointerdown', function(e) {
    if (e.button !== 0) return;
    var plot = e.target.closest && e.target.closest('#pm-voltage .vchart-plot');
    if (!plot || (e.target.closest && e.target.closest('.vchart-reset'))) return;
    var main = plot.querySelector('.vchart-main');
    if (!main) return;
    var meta = vchartMeta(main);
    vDrag = {
      id: e.pointerId,
      plot: plot,
      z: vZoom || vchartFull(meta),
      x: e.clientX,
      y: e.clientY
    };
    plot.classList.add('is-drag');
    if (plot.setPointerCapture) plot.setPointerCapture(e.pointerId);
  });

  document.addEventListener('pointermove', function(e) {
    var main = document.querySelector('#pm-voltage .vchart-main');
    var tip = document.querySelector('#pm-voltage .vchart-tip');
    if (main && tip && e.target.closest && e.target.closest('#pm-voltage .vchart-main')) {
      var metaTip = vchartMeta(main);
      var pt = vchartPoint(main, e.clientX, e.clientY);
      if (pt && pt.x >= 0 && pt.x <= metaTip.w && pt.y >= 0 && pt.y <= metaTip.plotH) {
        var tTip = metaTip.t0 + (pt.x / metaTip.w) * (metaTip.t1 - metaTip.t0);
        var vTip = metaTip.y1 - (pt.y / metaTip.plotH) * (metaTip.y1 - metaTip.y0);
        var when = new Date(tTip * 1000).toLocaleString('uk-UA', {
          timeZone: 'Europe/Kyiv', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'
        });
        tip.hidden = false;
        tip.textContent = when + ' · ' + Math.round(vTip) + ' В';
        var box = main.getBoundingClientRect();
        var left = e.clientX - box.left + 12;
        if (left > box.width - 120) left = e.clientX - box.left - 120;
        tip.style.left = left + 'px';
        tip.style.top = (e.clientY - box.top + 12) + 'px';
      }
    } else if (tip && !(e.target.closest && e.target.closest('#pm-voltage .vchart-plot'))) {
      tip.hidden = true;
    }
    if (!vDrag || e.pointerId !== vDrag.id || !main) return;
    var meta = vchartMeta(main);
    var rect = main.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    var z0 = vDrag.z;
    var dt = (e.clientX - vDrag.x) / rect.width * (z0.t1 - z0.t0);
    var next = { t0: z0.t0 - dt, t1: z0.t1 - dt, y0: meta.y0, y1: meta.y1 };
    vZoom = vchartClamp(next, meta);
    if (vchartIsFull(vZoom, meta)) vZoom = null;
    vchartApply();
  });

  function vchartEndDrag(e) {
    if (!vDrag || (e && e.pointerId !== vDrag.id)) return;
    if (vDrag.plot) vDrag.plot.classList.remove('is-drag');
    vDrag = null;
  }
  document.addEventListener('pointerup', vchartEndDrag);
  document.addEventListener('pointercancel', vchartEndDrag);

  document.addEventListener('dblclick', function(e) {
    if (!(e.target.closest && e.target.closest('#pm-voltage .vchart-plot, #pm-voltage .vchart-strip'))) return;
    vZoom = null;
    vchartApply();
  });

  document.addEventListener('click', function(e) {
    if (e.target.closest && e.target.closest('#pm-voltage .vchart-reset')) {
      vZoom = null;
      vchartApply();
      return;
    }
    if (e.target.closest && e.target.closest('#pm-voltage .vchart-full')) {
      vchartToggleFullscreen();
      return;
    }
    var helpBtn = e.target.closest && e.target.closest('#pm-voltage .vchart-help');
    var pop = document.querySelector('#pm-voltage .vchart-help-pop');
    if (helpBtn && pop) {
      var open = pop.hidden;
      pop.hidden = !open;
      helpBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
      return;
    }
    if (pop && !pop.hidden && !(e.target.closest && e.target.closest('#pm-voltage .vchart-help-pop'))) {
      pop.hidden = true;
      var help = document.querySelector('#pm-voltage .vchart-help');
      if (help) help.setAttribute('aria-expanded', 'false');
    }
    var dayBtn = e.target.closest && e.target.closest('#pm-voltage .vchart-day');
    if (!dayBtn || dayBtn.disabled) return;
    var dir = +dayBtn.getAttribute('data-dir');
    if (!dir) return;
    vShift = Math.max(0, vShift - dir);
    vZoom = null;
    try { sessionStorage.setItem('pm_vchart_shift', String(vShift)); } catch (err) {}
    vchartReload();
  });

  document.addEventListener('keydown', function(e) {
    if (e.key !== 'Escape') return;
    var pop = document.querySelector('#pm-voltage .vchart-help-pop');
    if (!pop || pop.hidden) return;
    e.preventDefault();
    pop.hidden = true;
    var help = document.querySelector('#pm-voltage .vchart-help');
    if (help) help.setAttribute('aria-expanded', 'false');
  });

  vchartApply();

  // Fragment fetch + live update
  document.body.classList.add('pm-ready');
  if (key) {
    var urlBase = '/api/dashboard-fragments?key=' + encodeURIComponent(key);
    var keyExpiredShown = false;
    function showKeyExpired() {
      if (keyExpiredShown) return;
      keyExpiredShown = true;
      var banner = document.createElement('div');
      banner.className = 'pm-key-expired';
      banner.style.cssText = 'position:fixed;inset:0;background:rgba(15,23,42,0.95);z-index:9999;display:flex;align-items:center;justify-content:center;flex-direction:column;padding:1.5rem;text-align:center';
      banner.innerHTML = '<p style="font-size:1.2rem;margin:0 0 1rem;color:#f87171">\u26a0\ufe0f Термін дії посилання закінчився</p>' +
        '<p style="color:var(--muted);margin:0;max-width:320px">Отримайте нове посилання там, де отримали це.</p>';
      document.body.appendChild(banner);
    }
    function doFetch() {
      var requestedShift = vShift;
      var url = urlBase + '&chart_shift=' + requestedShift + '&_=' + Date.now();
      fetch(url, { cache: 'no-store' }).then(function(r) {
        if (r.status === 403) {
          showKeyExpired();
          return null;
        }
        return r.json();
      }).then(function(d) {
        if (!d || requestedShift !== vShift) return;
        var el;
        if (d.pm_status_block) {
          el = document.getElementById('pm-status-block');
          if (el) {
            el.innerHTML = d.pm_status_block;
            var isDown = !!el.querySelector('.status.down');
            document.body.setAttribute('data-pm-down', isDown ? '1' : '0');
            updScheduleNow();
          }
        }
        if (d.pm_sched !== undefined) {
          el = document.getElementById('pm-sched-content');
          if (el) {
            el.innerHTML = d.pm_sched;
            updScheduleNow();
          }
        }
        if (d.pm_weather !== undefined) { el = document.getElementById('pm-weather'); if (el) el.innerHTML = d.pm_weather; }
        if (d.pm_alert !== undefined) { el = document.getElementById('pm-alert'); if (el) el.innerHTML = d.pm_alert; }
        if (d.pm_ev_tbody !== undefined) { el = document.getElementById('pm-events-tbody'); if (el) el.innerHTML = d.pm_ev_tbody; }
        if (d.pm_hb_tbody !== undefined) { el = document.getElementById('pm-hb-tbody'); if (el) el.innerHTML = d.pm_hb_tbody; }
        if (d.pm_tg_tbody !== undefined) { el = document.getElementById('pm-tg-tbody'); if (el) el.innerHTML = d.pm_tg_tbody; }
        if (d.pm_alert_ev_tbody !== undefined) { el = document.getElementById('pm-alert-events-tbody'); if (el) el.innerHTML = d.pm_alert_ev_tbody; }
        if (d.pm_voltage !== undefined) {
          el = document.getElementById('pm-voltage');
          if (el) {
            el.innerHTML = d.pm_voltage;
            var chart = el.querySelector('.vchart');
            if (chart) {
              var shown = +chart.getAttribute('data-shift');
              if (isFinite(shown) && shown !== vShift) {
                vShift = shown;
                try { sessionStorage.setItem('pm_vchart_shift', String(vShift)); } catch (err) {}
              }
            }
            vchartApply();
          }
        }
        if (d.pm_ver !== undefined) {
          el = document.getElementById('pm-ver-content');
          if (el) el.innerHTML = d.pm_ver;
        }
        if (d.pm_breakers !== undefined) {
          el = document.getElementById('pm-breakers-live');
          if (el && el.innerHTML !== d.pm_breakers) {
            el.innerHTML = d.pm_breakers;
            if (window.pmRefreshBreakers) window.pmRefreshBreakers();
          }
        }
        if (d.pm_deye) {
          el = document.getElementById('pm-deye');
          if (el) {
            var openStates = {};
            el.querySelectorAll('details').forEach(function(det) {
              var key = det.getAttribute('data-ls-key');
              if (key) openStates[key] = det.open;
              else {
                var sum = det.querySelector('summary');
                if (sum) {
                  var m = sum.textContent.match(/^(\d{4}-\d{2}-\d{2})/);
                  if (m) openStates['day_' + m[1]] = det.open;
                }
              }
            });
            el.innerHTML = d.pm_deye;
            el.querySelectorAll('details').forEach(function(det) {
              var key = det.getAttribute('data-ls-key');
              if (key) {
                var saved = localStorage.getItem(key);
                det.open = saved !== null ? (saved === '1') : (det.getAttribute('data-default-open') === '1');
                if (!det.dataset.pmInited) {
                  det.dataset.pmInited = '1';
                  det.addEventListener('toggle', function() { localStorage.setItem(key, det.open ? '1' : '0'); });
                }
              } else {
                var sum = det.querySelector('summary');
                if (sum) {
                  var m = sum.textContent.match(/^(\d{4}-\d{2}-\d{2})/);
                  if (m && openStates['day_' + m[1]] !== undefined) det.open = openStates['day_' + m[1]];
                }
              }
            });
          }
        }
        if (d.pm_mk) { el = document.getElementById('pm-mk-wrap'); if (el) el.innerHTML = d.pm_mk; }
        if (d.title) document.title = d.title;
        if (d.favicon) {
          var old = document.querySelector('link[rel="icon"]');
          if (old) old.remove();
          var link = document.createElement('link');
          link.rel = 'icon';
          link.type = 'image/png';
          link.href = '/icons/' + d.favicon + '?t=' + Date.now();
          document.head.appendChild(link);
        }
      }).catch(function() {});
    }
    vchartReload = doFetch;
    var fetchInterval = setInterval(function() {
      doFetch();
      if (keyExpiredShown) clearInterval(fetchInterval);
    }, 10000);
    setTimeout(doFetch, 500);
  }

  var breakerBoard = document.getElementById('pm-breakers-board');
  if (breakerBoard && key) {
    var breakerDate = kyivTodayBreaker();
    var breakerTimer = 0;

    function kyivTodayBreaker() {
      return new Intl.DateTimeFormat('en-CA', {
        timeZone: 'Europe/Kyiv', year: 'numeric', month: '2-digit', day: '2-digit'
      }).format(new Date());
    }
    function pad2(n) { return (n < 10 ? '0' : '') + n; }
    function shiftBreakerDay(iso, days) {
      var parts = iso.split('-');
      var shifted = new Date(Date.UTC(+parts[0], +parts[1] - 1, +parts[2] + days));
      return shifted.getUTCFullYear() + '-' + pad2(shifted.getUTCMonth() + 1) + '-' + pad2(shifted.getUTCDate());
    }
    function breakerNowFrac(data) {
      if (!data || data.date !== kyivTodayBreaker() || !data.start || !data.end) return null;
      var frac = (Date.now() / 1000 - data.start) / (data.end - data.start);
      if (frac < 0) frac = 0;
      if (frac > 1) frac = 1;
      return frac;
    }
    function paintBreakerNow(data) {
      var frac = breakerNowFrac(data);
      var hourNow = null;
      if (frac !== null) {
        var parts = {};
        new Intl.DateTimeFormat('en-GB', {
          timeZone: 'Europe/Kyiv', hour: '2-digit', hourCycle: 'h23'
        }).formatToParts(new Date()).forEach(function(p) { parts[p.type] = p.value; });
        hourNow = parseInt(parts.hour, 10);
        if (hourNow === 24) hourNow = 0;
      }
      breakerBoard.querySelectorAll('[data-brk-hour]').forEach(function(el) {
        el.classList.toggle('brk-hour-now', hourNow !== null && +el.getAttribute('data-brk-hour') === hourNow);
      });
      breakerBoard.querySelectorAll('.brk-now').forEach(function(el) {
        if (frac === null) el.style.display = 'none';
        else { el.style.display = ''; el.style.left = (frac * 100).toFixed(2) + '%'; }
      });
    }
    function breakerOnPieces(span, downs) {
      var cuts = [span.start, span.end];
      downs.forEach(function(gap) {
        if (gap[1] <= span.start || gap[0] >= span.end) return;
        cuts.push(Math.max(span.start, gap[0]));
        cuts.push(Math.min(span.end, gap[1]));
      });
      cuts.sort(function(a, b) { return a - b; });
      var points = [];
      cuts.forEach(function(t) {
        if (!points.length || points[points.length - 1] !== t) points.push(t);
      });
      var pieces = [];
      for (var i = 0; i < points.length - 1; i++) {
        var left = points[i];
        var right = points[i + 1];
        if (right <= left) continue;
        var mid = (left + right) / 2;
        var onBattery = downs.some(function(gap) { return gap[0] <= mid && mid < gap[1]; });
        pieces.push({ kind: onBattery ? 'brk-batt' : 'brk-on', start: left, end: right });
      }
      return pieces;
    }
    function breakerClockMinutes(text) {
      var parts = String(text || '').split(':');
      if (parts.length !== 2) return null;
      var hour = parseInt(parts[0], 10);
      var minute = parseInt(parts[1], 10);
      if (!isFinite(hour) || !isFinite(minute)) return null;
      if (hour === 24 && minute === 0) return 1440;
      if (hour < 0 || hour > 23 || minute < 0 || minute > 59) return null;
      return hour * 60 + minute;
    }
    function breakerLane(title, bars, empty) {
      return '<div class="brk-track"><span class="brk-track-name">' + title + '</span>' +
        '<div class="brk-lane-wrap">' + (empty || '') + '<div class="brk-lane">' + bars +
        '<i class="brk-now"></i></div></div></div>';
    }
    function breakerPlanLane(data) {
      var queue = data.schedule_queue || '5.1';
      var title = 'Графік ' + queue;
      var grid = data.schedule;
      if (!grid || grid.length !== 48) {
        return breakerLane(title, '', '<div class="brk-empty">' + title + ': немає знімка</div>');
      }
      var bars = '';
      var index = 0;
      while (index < 48) {
        var status = grid[index] === 'ok' ? 'ok' : 'off';
        var end = index + 1;
        while (end < 48 && (grid[end] === 'ok' ? 'ok' : 'off') === status) end += 1;
        var left = index / 48 * 100;
        var width = (end - index) / 48 * 100;
        bars += '<i class="brk-bar brk-plan-' + status + '" style="left:' + left.toFixed(2) + '%;width:' + width.toFixed(2) + '%"></i>';
        index = end;
      }
      return breakerLane(title, bars, '');
    }
    function breakerBoilerLane(data) {
      var title = 'Котельня';
      var intervals = data.boiler;
      if (!intervals || !intervals.length) {
        return breakerLane(title, '', '<div class="brk-empty">' + title + ': немає графіка</div>');
      }
      var bars = '';
      intervals.forEach(function(pair) {
        if (!pair || pair.length !== 2) return;
        var start = breakerClockMinutes(pair[0]);
        var end = breakerClockMinutes(pair[1]);
        if (start === null || end === null || end <= start) return;
        var left = start / 1440 * 100;
        var width = Math.min(100 - left, (end - start) / 1440 * 100);
        if (width <= 0) return;
        bars += '<i class="brk-bar brk-boiler" style="left:' + left.toFixed(2) + '%;width:' + width.toFixed(2) + '%"></i>';
      });
      if (!bars) return breakerLane(title, '', '<div class="brk-empty">' + title + ': немає графіка</div>');
      return breakerLane(title, bars, '');
    }
    function paintBreakers(data) {
      var startMs = (data.start || 0) * 1000;
      var spanMs = ((data.end || 0) - (data.start || 0)) * 1000 || 86400000;
      var pretty = data.date.split('-');
      var html = '<div class="brk-nav"><a href="#brk-prev" id="brk-prev">‹</a> <span id="brk-date">' +
        pretty[2] + '.' + pretty[1] + '.' + pretty[0] + '</span> <a href="#brk-next" id="brk-next">›</a></div>';
      html += '<div class="brk-chart"><div class="brk-hours">';
      for (var hour = 0; hour < 24; hour++) {
        html += '<span data-brk-hour="' + hour + '">' + (hour < 10 ? '0' : '') + hour + '</span>';
      }
      html += '</div><div class="brk-plot">';
      [['svitlo', 'Освітлення', 'Світло'], ['itp', 'Обігрів', 'ІТП']].forEach(function(item) {
        var device = data.devices[item[0]] || { ready: false };
        var spans = device.ready ? (device.spans || []) : [];
        var bars = '';
        var empty = spans.length ? '' : '<div class="brk-empty">' + item[2] + ': ще немає знімка</div>';
        spans.forEach(function(span) {
          if (span.end == null) return;
          var pieces = span.switch ? breakerOnPieces(span, data.grid_down || []) : [{ kind: 'brk-off', start: span.start, end: span.end }];
          pieces.forEach(function(piece) {
            var left = (piece.start * 1000 - startMs) / spanMs * 100;
            var width = ((piece.end - piece.start) * 1000) / spanMs * 100;
            left = Math.min(100, Math.max(0, left));
            width = Math.min(100 - left, Math.max(0, width));
            if (width <= 0) return;
            bars += '<i class="brk-bar ' + piece.kind + '" style="left:' + left.toFixed(2) + '%;width:' + width.toFixed(2) + '%"></i>';
          });
        });
        html += '<div class="brk-track"><span class="brk-track-name">' + item[1] + '</span>' +
          '<div class="brk-lane-wrap">' + empty + '<div class="brk-lane">' + bars +
          '<i class="brk-now"></i></div></div></div>';
      });
      html += breakerPlanLane(data);
      html += breakerBoilerLane(data);
      html += '</div><div class="brk-legend"><i class="brk-key brk-on"></i> увімкнено, було світло <i class="brk-key brk-batt"></i> увімкнено, не було світла <i class="brk-key brk-off"></i> вимкнено <i class="brk-key brk-plan-ok"></i> графік: є світло <i class="brk-key brk-plan-off"></i> немає <i class="brk-key brk-boiler"></i> котельня</div></div>';
      breakerBoard.innerHTML = html;
      paintBreakerNow(data);
      var prev = document.getElementById('brk-prev');
      var next = document.getElementById('brk-next');
      if (prev) prev.addEventListener('click', function(e) {
        e.preventDefault();
        loadBreakers(shiftBreakerDay(breakerDate, -1));
      });
      if (next) next.addEventListener('click', function(e) {
        e.preventDefault();
        loadBreakers(shiftBreakerDay(breakerDate, 1));
      });
    }
    var breakerPayload = null;
    function loadBreakers(date) {
      breakerDate = date || kyivTodayBreaker();
      var url = '/api/breakers?key=' + encodeURIComponent(key) + '&day=' + encodeURIComponent(breakerDate);
      fetch(url, { cache: 'no-store' }).then(function(r) { return r.ok ? r.json() : null; }).then(function(data) {
        if (!data || data.date !== breakerDate) return;
        breakerPayload = data;
        paintBreakers(data);
      }).catch(function() {});
    }
    window.pmRefreshBreakers = function() {
      if (breakerDate === kyivTodayBreaker()) loadBreakers(breakerDate);
    };
    loadBreakers(breakerDate);
    setInterval(function() {
      if (breakerPayload) paintBreakerNow(breakerPayload);
    }, 10000);
    breakerTimer = setInterval(function() {
      if (breakerDate === kyivTodayBreaker()) loadBreakers(breakerDate);
    }, 60000);
    document.addEventListener('visibilitychange', function() {
      if (!document.hidden) window.pmRefreshBreakers();
    });
    void breakerTimer;
  }
})();
