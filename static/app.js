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

  // Voltage chart: wheel zoom and drag, kept across the 10s refresh.
  var vZoom = null;
  var vDrag = null;

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
  }

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
    var v = meta.y1 - (pt.y / meta.plotH) * (meta.y1 - meta.y0);
    var next = {
      t0: t - (t - z.t0) * factor,
      t1: t + (z.t1 - t) * factor,
      y0: z.y0,
      y1: z.y1
    };
    if (!svg.classList.contains('vchart-strip')) {
      next.y0 = v - (v - z.y0) * factor;
      next.y1 = v + (z.y1 - v) * factor;
    }
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
      y: e.clientY,
      yToo: !(e.target.closest && e.target.closest('.vchart-strip'))
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
    var next = { t0: z0.t0 - dt, t1: z0.t1 - dt, y0: z0.y0, y1: z0.y1 };
    if (vDrag.yToo) {
      var dy = (e.clientY - vDrag.y) / rect.height * (z0.y1 - z0.y0);
      next.y0 = z0.y0 + dy;
      next.y1 = z0.y1 + dy;
    }
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
    if (!(e.target.closest && e.target.closest('#pm-voltage .vchart-reset'))) return;
    vZoom = null;
    vchartApply();
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
          if (el) {
            el.innerHTML = d.pm_voltage;
            vchartApply();
          }
        }
        if (d.pm_ver !== undefined) {
          el = document.getElementById('pm-ver-content');
          if (el) el.innerHTML = d.pm_ver;
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
