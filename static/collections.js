/* Building participation heatmap. Bits: lifts, water, heat, fuel, water battery. Apt 1 is index 0. */
(function () {
  'use strict';

  var root = document.getElementById('pm-collections');
  if (!root) return;

  var MASKS = [6,6,0,6,4,5,2,6,7,0,31,6,4,0,4,0,7,0,2,4,6,6,0,15,0,31,31,4,0,31,15,31,31,4,0,30,2,30,31,0,31,31,0,30,31,0,15,30,28,30,4,0,31,31,31,0,30,0,31,30,30,31,31,31,31,4,15,30,30,31,30,4,30,31,30,30,31,30,2,30,31,0,30,4,0,30,3,0,31,31,12,31,31,0,0,31,31,11,31,31,30,31,31,30,31,0,31,31,31,0,0,30,1,30,31,0,8,31,31,31,30,0,31,31,31,31,0,31,0,31,30,31,31,31,31,30,31,30,28,6,30,30,31,31,31,0,31,0,31,31,30,31,5,0,30,30,31,0,31,0,31,12,14,0,31,31,31,31,31,30,12,31,0,30,31,30,30,30,31,0,31,0,31,31,31,31,30,31,0,0,0,31];
  var OFFICES = [['оф60', 30], ['оф61', 30], ['оф62', 30], ['оф63', 30], ['оф64', 30]];
  var SHOPS = [['ГрінФіт', 4], ['Ком', 0], ['Амеда', 4], ['Фудпод', 0], ['Ком 2', 4]];
  var COLS = [
    { key: 'lifts', label: 'Ліфти', bit: 16 },
    { key: 'water', label: 'Вода', bit: 8 },
    { key: 'heat', label: 'Опалення', bit: 4 },
    { key: 'fuel', label: 'Паливо', bit: 2 },
    { key: 'battery', label: 'Вода АКБ', bit: 1 }
  ];
  var FILTER_KEY = 'pm_collection_filters';
  var filters = {};
  try { filters = JSON.parse(localStorage.getItem(FILTER_KEY) || '{}') || {}; } catch (e) { filters = {}; }
  COLS.forEach(function (col) {
    if (typeof filters[col.key] !== 'boolean') filters[col.key] = true;
  });
  var selected = '';

  function bits() {
    return COLS.filter(function (col) { return filters[col.key]; }).map(function (col) { return col.bit; });
  }

  function paid(mask, active) {
    return active.reduce(function (sum, bit) { return sum + ((mask & bit) === bit ? 1 : 0); }, 0);
  }

  function fill(score, total) {
    if (!total || !score) return '#000000';
    var level = Math.max(1, Math.min(5, Math.round((score / total) * 5)));
    return ['#000000', '#ef4444', '#f97316', '#eab308', '#bbf7d0', '#166534'][level];
  }

  function names(mask) {
    var list = COLS.filter(function (col) { return (mask & col.bit) === col.bit; }).map(function (col) { return col.label; });
    return list.length ? list.join(', ') : 'жодним збором';
  }

  function unitButton(id, mask, active) {
    var total = active.length;
    var score = total ? paid(mask, active) : 0;
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'col-cell' + (selected === id ? ' active' : '');
    btn.title = id + ': ' + score + ' з ' + (total || '—');
    btn.style.background = fill(score, total);
    btn.addEventListener('click', function () {
      selected = selected === id ? '' : id;
      render();
    });
    return btn;
  }

  function row(floor, units, note, active, center) {
    var line = document.createElement('div');
    line.className = 'col-row';
    var label = document.createElement('div');
    label.className = 'col-floor';
    label.textContent = floor;
    var cells = document.createElement('div');
    cells.className = 'col-cells' + (center ? ' center' : '');
    units.forEach(function (unit) { cells.appendChild(unitButton(unit[0], unit[1], active)); });
    var aside = document.createElement('div');
    aside.className = 'col-note';
    aside.textContent = note;
    line.appendChild(label);
    line.appendChild(cells);
    line.appendChild(aside);
    return line;
  }

  function render() {
    var active = bits();
    var total = active.length;
    var full = 0;
    var none = 0;
    MASKS.forEach(function (mask) {
      var score = total ? paid(mask, active) : 0;
      if (!total || score === 0) none += 1;
      else if (score === total) full += 1;
    });
    var partial = 192 - full - none;
    root.innerHTML = '';

    var lead = document.createElement('p');
    lead.className = 'col-lead';
    lead.textContent = 'Чорний — не брав участі. Червоний — мінімум, блідо-зелений — 4 з 5, глибокий зелений — усі.';
    root.appendChild(lead);

    var filtersRow = document.createElement('div');
    filtersRow.className = 'col-filters';
    COLS.forEach(function (col) {
      var label = document.createElement('label');
      var input = document.createElement('input');
      input.type = 'checkbox';
      input.checked = !!filters[col.key];
      input.addEventListener('change', function () {
        filters[col.key] = input.checked;
        localStorage.setItem(FILTER_KEY, JSON.stringify(filters));
        render();
      });
      label.appendChild(input);
      label.appendChild(document.createTextNode(col.label));
      filtersRow.appendChild(label);
    });
    root.appendChild(filtersRow);

    var stats = document.createElement('div');
    stats.className = 'col-stats';
    stats.textContent = 'Усі увімкнені: ' + full + ' · Частина: ' + partial + ' · Жодного: ' + none + ' · У розрахунку: ' + total + ' з 5';
    root.appendChild(stats);

    var building = document.createElement('div');
    building.className = 'col-building';

    var roof = document.createElement('div');
    roof.className = 'col-roof';
    roof.innerHTML = '<span class="col-roof-peak"></span><span>27</span>';
    building.appendChild(roof);
    building.appendChild(row('П 26', OFFICES, 'Офіси', active, true));

    var rule = document.createElement('div');
    rule.className = 'col-rule';
    building.appendChild(rule);

    for (var floor = 25; floor >= 2; floor--) {
      var start = (floor - 2) * 8 + 1;
      var units = [];
      for (var offset = 0; offset < 8; offset++) {
        var apt = start + offset;
        units.push([String(apt), MASKS[apt - 1]]);
      }
      building.appendChild(row('П ' + String(floor).padStart(2, '0'), units, 'кв.' + start + '–' + (start + 7), active));
    }

    var rule2 = document.createElement('div');
    rule2.className = 'col-rule';
    building.appendChild(rule2);
    building.appendChild(row('П 01', SHOPS, 'Комерція', active));
    root.appendChild(building);

    var legend = document.createElement('div');
    legend.className = 'col-legend';
    var steps = total ? total + 1 : 1;
    for (var step = 0; step < steps; step++) {
      var item = document.createElement('span');
      var swatch = document.createElement('span');
      swatch.className = 'col-swatch';
      swatch.style.background = fill(step, total);
      item.appendChild(swatch);
      item.appendChild(document.createTextNode(total ? (step + ' з ' + total) : 'збір вимкнено'));
      legend.appendChild(item);
    }
    root.appendChild(legend);

    if (selected) {
      var found = lookup(selected);
      if (found) {
        var detail = document.createElement('div');
        detail.className = 'col-detail';
        var score = total ? paid(found.mask, active) : 0;
        detail.innerHTML = '<b>' + found.id + '</b><br>' +
          (total ? (score + ' з ' + total + ' увімкнених') : 'Увімкніть хоча б один збір.') +
          '<br><small>Плюс у таблиці: ' + names(found.mask) + '</small>';
        root.appendChild(detail);
      }
    }

    var source = document.createElement('p');
    source.className = 'col-lead';
    source.textContent = 'Зріз 7 листопада 2026. Для «Вода АКБ» плюс означає щонайменше 2 000 грн готівкою або на банку.';
    root.appendChild(source);
  }

  function lookup(id) {
    var apt = parseInt(id, 10);
    if (apt >= 1 && apt <= 192 && String(apt) === id) return { id: 'кв. ' + apt, mask: MASKS[apt - 1] };
    var lists = [OFFICES, SHOPS];
    for (var i = 0; i < lists.length; i++) {
      for (var j = 0; j < lists[i].length; j++) {
        if (lists[i][j][0] === id) return { id: id, mask: lists[i][j][1] };
      }
    }
    return null;
  }

  render();
})();
