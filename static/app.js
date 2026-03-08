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

  // Fragment fetch + live update
  document.body.classList.add('pm-ready');
  var key = document.body.getAttribute('data-pm-key') || '';
  if (key) {
    var urlBase = '/api/dashboard-fragments?key=' + encodeURIComponent(key);
    function doFetch() {
      var url = urlBase + '&_=' + Date.now();
      fetch(url, { cache: 'no-store' }).then(function(r) { return r.json(); }).then(function(d) {
        var el;
        if (d.pm_status_block) { el = document.getElementById('pm-status-block'); if (el) el.innerHTML = d.pm_status_block; }
        if (d.pm_weather !== undefined) { el = document.getElementById('pm-weather'); if (el) el.innerHTML = d.pm_weather; }
        if (d.pm_alert !== undefined) { el = document.getElementById('pm-alert'); if (el) el.innerHTML = d.pm_alert; }
        if (d.pm_ev_tbody !== undefined) { el = document.getElementById('pm-events-tbody'); if (el) el.innerHTML = d.pm_ev_tbody; }
        if (d.pm_hb_tbody !== undefined) { el = document.getElementById('pm-hb-tbody'); if (el) el.innerHTML = d.pm_hb_tbody; }
        if (d.pm_tg_tbody !== undefined) { el = document.getElementById('pm-tg-tbody'); if (el) el.innerHTML = d.pm_tg_tbody; }
        if (d.pm_alert_ev_tbody !== undefined) { el = document.getElementById('pm-alert-events-tbody'); if (el) el.innerHTML = d.pm_alert_ev_tbody; }
        if (d.pm_deye) {
          el = document.getElementById('pm-deye');
          if (el) {
            el.innerHTML = d.pm_deye;
            var dt = document.getElementById('deye_table_details');
            if (dt && !dt.dataset.pmInited) {
              dt.dataset.pmInited = '1';
              dt.open = (localStorage.getItem('deye_table_open') !== '0');
              dt.addEventListener('toggle', function() { localStorage.setItem('deye_table_open', dt.open ? '1' : '0'); });
            }
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
    setInterval(doFetch, 10000);
    setTimeout(doFetch, 500);
  }
})();
