/* Building participation heatmap. Bits: lifts, water, heat, fuel, water battery. Apt 1 is index 0. */
(function () {
  'use strict';

  var root = document.getElementById('pm-collections');
  if (!root) return;

  var MASKS = [6,6,0,6,4,5,2,6,7,0,31,6,4,0,4,0,7,0,2,4,6,6,0,15,0,31,31,4,0,31,15,31,31,4,0,30,3,30,31,0,31,31,0,30,31,0,15,30,28,30,4,0,31,31,31,0,30,0,31,30,30,31,31,31,31,4,15,30,30,31,30,4,30,31,30,30,31,30,2,30,31,0,30,4,0,30,3,0,31,31,12,31,31,0,0,31,31,11,31,31,30,31,31,30,31,0,31,31,31,0,0,30,1,30,31,0,8,31,31,31,30,0,31,31,31,31,0,31,0,31,30,31,31,31,31,30,31,30,28,6,30,30,31,31,31,0,31,0,31,31,30,31,5,0,30,30,31,0,31,0,31,12,14,0,31,31,31,31,31,30,12,31,0,30,31,30,30,30,31,0,31,0,31,31,31,31,30,31,0,0,0,31];
  var OFFICES = [['оф60', 30], ['оф61', 30], ['оф62', 30], ['оф63', 30], ['оф64', 30]];
  var SHOPS = [['ГрінФіт', 4], ['Ком', 0], ['Амеда', 4], ['Фудпод', 0], ['Ком 2', 4]];
  var DEBTS = {
    '14': 14764.94, '32': 5123.97, '46': 14781.29, '52': 36524.24,
    '68': 24115.63, '69': 16165.99, '72': 6686.05, '100': 9641.61,
    '116': 25733.82, '129': 22792.66, '132': 5766.44, '140': 6885.86,
    '144': 28315.12, '146': 5856.03, '154': 5856.03, '182': 62462.09,
    '191': 9992.13
  };
  var DEBT_KEY = 'pm_collection_debt';
  var showDebt = true;
  try { showDebt = localStorage.getItem(DEBT_KEY) !== '0'; } catch (e) { showDebt = true; }
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

  function formatUah(value) {
    var parts = value.toFixed(2).split('.');
    return parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, '\u00a0') + ',' + parts[1] + ' грн';
  }

  function debtOf(id) {
    return Object.prototype.hasOwnProperty.call(DEBTS, id) ? DEBTS[id] : null;
  }

  function floorOf(id) {
    if (String(id).indexOf('оф') === 0) return '26';
    if (id === 'ГрінФіт' || id === 'Ком' || id === 'Амеда' || id === 'Фудпод' || id === 'Ком 2') return '1';
    var apartment = parseInt(id, 10);
    if (String(apartment) !== String(id) || apartment < 1 || apartment > 192) return '';
    return String(Math.floor((apartment - 1) / 8) + 2);
  }

  function unitHint(id, mask, active) {
    var title = String(parseInt(id, 10)) === String(id) ? ('кв. ' + id) : id;
    var floor = floorOf(id);
    var total = active.length;
    var score = total ? paid(mask, active) : 0;
    var debt = debtOf(id);
    var lines = COLS.map(function (col) {
      return col.label + ': ' + (((mask & col.bit) === col.bit) ? 'так' : 'ні');
    });
    return [
      floor ? (title + ', поверх ' + floor) : title,
      total ? (score + ' з ' + total + ' увімкнених') : 'Усі збори вимкнені',
    ].concat(lines).concat([debt === null ? 'Борг Оселі: немає' : ('Борг Оселі: ' + formatUah(debt))]).join('\n');
  }

  function unitButton(id, mask, active) {
    var total = active.length;
    var score = total ? paid(mask, active) : 0;
    var debt = debtOf(id);
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'col-cell' + (selected === id ? ' active' : '');
    var hint = unitHint(id, mask, active);
    btn.style.background = fill(score, total);
    btn.addEventListener('mouseenter', function (event) { showTip(hint, event); });
    btn.addEventListener('mousemove', function (event) { moveTip(event); });
    btn.addEventListener('mouseleave', hideTip);
    if (showDebt && debt !== null) {
      var mark = document.createElement('span');
      mark.className = 'col-debt';
      mark.textContent = '!';
      btn.appendChild(mark);
    }
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

  var tip = document.createElement('div');
  tip.className = 'col-tip';
  tip.hidden = true;
  document.body.appendChild(tip);

  function showTip(text, event) {
    tip.textContent = text;
    tip.hidden = false;
    moveTip(event);
  }

  function moveTip(event) {
    var x = event.clientX + 14;
    var y = event.clientY + 16;
    tip.style.left = x + 'px';
    tip.style.top = y + 'px';
    var rect = tip.getBoundingClientRect();
    if (rect.right > window.innerWidth - 8) tip.style.left = (event.clientX - rect.width - 14) + 'px';
    if (rect.bottom > window.innerHeight - 8) tip.style.top = (event.clientY - rect.height - 12) + 'px';
  }

  function hideTip() {
    tip.hidden = true;
  }

  function render() {
    hideTip();
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

    var debtRow = document.createElement('div');
    debtRow.className = 'col-filters';
    var debtLabel = document.createElement('label');
    var debtInput = document.createElement('input');
    debtInput.type = 'checkbox';
    debtInput.checked = showDebt;
    debtInput.addEventListener('change', function () {
      showDebt = debtInput.checked;
      try { localStorage.setItem(DEBT_KEY, showDebt ? '1' : '0'); } catch (e) {}
      render();
    });
    debtLabel.appendChild(debtInput);
    debtLabel.appendChild(document.createTextNode('Борг Оселі'));
    debtRow.appendChild(debtLabel);
    var debtNote = document.createElement('span');
    debtNote.textContent = 'Знак ! не змінює колір. Клік по клітинці показує суму.';
    debtRow.appendChild(debtNote);
    root.appendChild(debtRow);

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
        var debt = debtOf(selected);
        detail.innerHTML = '<b>' + found.id + '</b><br>' +
          (total ? (score + ' з ' + total + ' увімкнених') : 'Увімкніть хоча б один збір.') +
          '<br><small>Плюс у таблиці: ' + names(found.mask) + '</small>' +
          (debt === null ? '' : '<br>Борг Оселі: ' + formatUah(debt));
        root.appendChild(detail);
      }
    }

    var source = document.createElement('p');
    source.className = 'col-lead';
    source.textContent = 'Зріз участі 7 листопада 2026. Борг — кабінет Оселі на 9 листопада 2026, 17 квартир. НЖ 67 (5 934,34 грн) на сітці немає.';
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
