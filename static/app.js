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
  var container = document.getElementById('dashboard-sections');
  if (container) {
    var order = JSON.parse(localStorage.getItem(ORDER_KEY) || 'null');
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

  // Plug control (Nous/Tuya)
  var key = document.body.getAttribute('data-pm-key') || '';
  var plugState = document.getElementById('plug-state');
  var plugBtnOn = document.getElementById('plug-btn-on');
  var plugBtnOff = document.getElementById('plug-btn-off');
  var plugLabels = { on: 'Увімкнено', off: 'Вимкнено', unknown: 'невідомо' };
  function updPlugState(s) { if (plugState) plugState.textContent = plugLabels[s] || s; }
  function plugSet(state) {
    if (!key) return;
    plugState.textContent = 'чекаємо...';
    fetch('/api/plug-set?key=' + encodeURIComponent(key) + '&state=' + state, { method: 'POST' })
      .then(function() {
        setTimeout(function() {
          fetch('/api/plug-status?key=' + encodeURIComponent(key))
            .then(function(r) { return r.json(); })
            .then(function(d) { updPlugState(d.state || 'unknown'); })
            .catch(function() { updPlugState('unknown'); });
        }, 3000);
      })
      .catch(function() { updPlugState('unknown'); });
  }
  if (plugBtnOn) plugBtnOn.addEventListener('click', function() { plugSet('on'); });
  if (plugBtnOff) plugBtnOff.addEventListener('click', function() { plugSet('off'); });

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

  // Fragment fetch + live update
  document.body.classList.add('pm-ready');
  if (key) {
    var urlBase = '/api/dashboard-fragments?key=' + encodeURIComponent(key);
    function doFetch() {
      var url = urlBase + '&_=' + Date.now();
      fetch(url, { cache: 'no-store' }).then(function(r) { return r.json(); }).then(function(d) {
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
        if (d.pm_plug_state !== undefined) updPlugState(d.pm_plug_state);
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
    setInterval(doFetch, 10000);
    setTimeout(doFetch, 500);
  }
})();
