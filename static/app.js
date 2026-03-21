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

  // Footer visibility (hash, online, key, admin)
  var FOOTER_VIS_KEY = 'pm_footer_vis';
  var FOOTER_PARTS = ['hash', 'online', 'key', 'admin'];
  function getFooterVis() {
    var raw = localStorage.getItem(FOOTER_VIS_KEY);
    var vis = {};
    try { vis = raw ? JSON.parse(raw) : {}; } catch (e) {}
    FOOTER_PARTS.forEach(function(p) { if (vis[p] === undefined) vis[p] = true; });
    return vis;
  }
  function setFooterVis(vis) {
    localStorage.setItem(FOOTER_VIS_KEY, JSON.stringify(vis));
  }
  function initFooterVisibility() {
    var vis = getFooterVis();
    var wrap = document.getElementById('pm-ver');
    if (!wrap) return;
    wrap.querySelectorAll('[data-pm-footer]').forEach(function(sp) {
      var part = sp.getAttribute('data-pm-footer');
      sp.style.display = vis[part] !== false ? '' : 'none';
    });
    var toggle = wrap.querySelector('.pm-footer-toggle');
    if (!toggle || toggle.dataset.pmInited) return;
    toggle.dataset.pmInited = '1';
    toggle.addEventListener('click', function(e) {
      e.preventDefault();
      var pop = wrap.querySelector('.pm-footer-popover');
      if (pop) {
        pop.remove();
        document.removeEventListener('click', closePop);
        return;
      }
      pop = document.createElement('div');
      pop.className = 'pm-footer-popover';
      var vis = getFooterVis();
      var html = '<div class="pm-footer-popover-title">Футер</div>';
      FOOTER_PARTS.forEach(function(p) {
        var label = { hash: 'Хеш', online: 'Онлайн', key: "Ім'я ключа", admin: 'Адмінка' }[p];
        var checked = vis[p] !== false ? ' checked' : '';
        html += '<label class="pm-footer-popover-item"><input type="checkbox" data-pm-footer="' + p + '"' + checked + '> ' + label + '</label>';
      });
      pop.innerHTML = html;
      toggle.parentNode.appendChild(pop);
      pop.addEventListener('click', function(ev) {
        if (ev.target.type !== 'checkbox') return;
        var p = ev.target.getAttribute('data-pm-footer');
        vis[p] = ev.target.checked;
        setFooterVis(vis);
        var sp = wrap.querySelector('[data-pm-footer="' + p + '"]');
        if (sp) sp.style.display = vis[p] !== false ? '' : 'none';
      });
      function closePop(ev) {
        if (!pop.contains(ev.target) && ev.target !== toggle) {
          pop.remove();
          document.removeEventListener('click', closePop);
        }
      }
      setTimeout(function() { document.addEventListener('click', closePop); }, 0);
    });
  }
  initFooterVisibility();

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

  var key = document.body.getAttribute('data-pm-key') || '';

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
      var url = urlBase + '&_=' + Date.now();
      fetch(url, { cache: 'no-store' }).then(function(r) {
        if (r.status === 403) {
          showKeyExpired();
          return null;
        }
        return r.json();
      }).then(function(d) {
        if (!d) return;
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
          if (el) el.innerHTML = d.pm_voltage;
        }
        if (d.pm_ver !== undefined) {
          el = document.getElementById('pm-ver-content');
          if (el) el.innerHTML = d.pm_ver;
          initFooterVisibility();
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
    var fetchInterval = setInterval(function() {
      doFetch();
      if (keyExpiredShown) clearInterval(fetchInterval);
    }, 10000);
    setTimeout(doFetch, 500);
  }
})();
