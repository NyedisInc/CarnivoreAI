(function () {
  'use strict';
  var F = RbLayerFields;
  var el = F.el;
  var DAY = /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/;

  function within(value, min, max) {
    return (min == null || value >= min) && (max == null || value <= max);
  }

  function fullOrder(item, list) {
    var ids = F.optionIds(item);
    return Array.isArray(list) && list.length === ids.length && ids.every(function (id) { return list.indexOf(id) >= 0; })
      && list.every(function (id, i) { return list.indexOf(id) === i; });
  }


  function listOrder(list) {
    return Array.prototype.map.call(list.children, function (li) { return li.getAttribute('data-rbl-id'); });
  }

  function slotAt(list, dragged, y) {
    var at = 0;
    Array.prototype.forEach.call(list.children, function (li) {
      if (li === dragged) return;
      var r = li.getBoundingClientRect();
      if (r.top + r.height / 2 < y) at++;
    });
    return at;
  }

  function place(list, li, to) {
    var others = Array.prototype.filter.call(list.children, function (n) { return n !== li; });
    list.insertBefore(li, others[to] || null);
  }

  function rank(item, value, api) {
    var list = el('ol', 'rbl-rank');
    var shown = fullOrder(item, value) ? value : (fullOrder(item, item.default) ? item.default : F.optionIds(item));
    var labels = {};
    item.options.forEach(function (o) { labels[o.id] = o.label; });

    function settle(announce) {
      Array.prototype.forEach.call(list.children, function (li, i) {
        li.querySelector('.rbl-rank__n').textContent = String(i + 1);
        li.setAttribute('aria-posinset', String(i + 1));
      });
      if (announce) api.change(listOrder(list));
    }

    function nudge(li, step, focus) {
      var from = listOrder(list).indexOf(li.getAttribute('data-rbl-id'));
      var to = from + step;
      if (to < 0 || to >= list.children.length) return;
      place(list, li, to);
      settle(true);
      focus.focus();
    }

    function entry(id) {
      var li = el('li', 'rbl-rank__item');
      li.setAttribute('data-rbl-id', id);
      li.setAttribute('aria-setsize', String(item.options.length));
      li.tabIndex = 0;
      var grip = el('span', 'rbl-rank__grip', '::');
      grip.setAttribute('aria-hidden', 'true');
      li.appendChild(grip);
      li.appendChild(el('span', 'rbl-rank__n'));
      li.appendChild(el('span', 'rbl-rank__label', labels[id]));
      [['rank_up', -1], ['rank_down', 1]].forEach(function (spec) {
        var b = el('button', 'rbl-key rbl-rank__move', api.str(spec[0]));
        b.type = 'button';
        b.setAttribute('aria-label', api.str(spec[0]) + ' ' + labels[id]);
        b.addEventListener('click', function () { nudge(li, spec[1], b); });
        li.appendChild(b);
      });
      li.addEventListener('keydown', function (e) {
        if (e.target !== li || (e.key !== 'ArrowUp' && e.key !== 'ArrowDown')) return;
        e.preventDefault();
        nudge(li, e.key === 'ArrowUp' ? -1 : 1, li);
      });
      grip.addEventListener('pointerdown', function (e) {
        if (e.button) return;
        e.preventDefault();
        if (grip.setPointerCapture) grip.setPointerCapture(e.pointerId);
        var before = listOrder(list).join();
        li.classList.add('rbl-rank__item--drag');
        function move(ev) {
          var to = slotAt(list, li, ev.clientY);
          if (listOrder(list).indexOf(id) !== to) place(list, li, to);
        }
        function done() {
          grip.removeEventListener('pointermove', move);
          grip.removeEventListener('pointerup', done);
          grip.removeEventListener('pointercancel', done);
          li.classList.remove('rbl-rank__item--drag');
          settle(listOrder(list).join() !== before);
        }
        grip.addEventListener('pointermove', move);
        grip.addEventListener('pointerup', done);
        grip.addEventListener('pointercancel', done);
      });
      return li;
    }

    list.setAttribute('role', 'list');
    shown.forEach(function (id) { list.appendChild(entry(id)); });
    settle(false);
    return list;
  }


  function clamp(item, n) {
    if (item.min != null && n < item.min) return item.min;
    if (item.max != null && n > item.max) return item.max;
    return n;
  }

  function number(item, value, api) {
    var wrap = el('div', 'rbl-num');
    var slider = item.slider === true && item.min != null && item.max != null;
    var field = el('input', slider ? 'rbl-range' : 'rbl-field rbl-numfield');
    field.type = slider ? 'range' : 'number';
    if (item.min != null) field.min = String(item.min);
    if (item.max != null) field.max = String(item.max);
    field.step = item.step != null ? String(item.step) : (slider ? '1' : 'any');
    var readout = el('span', 'rbl-num__read');
    var unit = item.unit ? el('span', 'rbl-num__unit', item.unit) : null;
    if (typeof value === 'number') field.value = String(value);
    else if (slider) field.value = String(item.min);
    readout.textContent = typeof value === 'number' ? String(value) : '';
    field.addEventListener('input', function () {
      var n = field.value === '' ? NaN : Number(field.value);
      if (!isFinite(n)) {
        readout.textContent = '';
        api.change(undefined);
        return;
      }
      var held = clamp(item, n);
      readout.textContent = String(held);
      api.change(held);
    });
    field.addEventListener('change', function () {
      var n = Number(field.value);
      if (field.value !== '' && isFinite(n) && clamp(item, n) !== n) field.value = String(clamp(item, n));
    });
    wrap.appendChild(field);
    if (slider) wrap.appendChild(readout);
    if (unit) wrap.appendChild(unit);
    return wrap;
  }


  function date(item, value, api) {
    var field = el('input', 'rbl-field rbl-datefield');
    field.type = 'date';
    if (item.min != null) field.min = item.min;
    if (item.max != null) field.max = item.max;
    var accepted = typeof value === 'string' ? value : '';
    field.value = accepted;
    field.addEventListener('change', function () {
      var day = field.value;
      if (day === '') {
        accepted = '';
        api.change(undefined);
      } else if (DAY.test(day) && within(day, item.min, item.max)) {
        accepted = day;
        api.change(day);
      } else {
        field.value = accepted;
      }
    });
    return field;
  }

  F.register('rank', {
    make: rank,
    initial: function (item) { return fullOrder(item, item.default) ? item.default.slice() : F.optionIds(item); },
    coerce: function (item, raw) { return fullOrder(item, raw) ? raw.slice() : undefined; },
    answered: function () { return true; }
  });
  F.register('number', {
    make: number,
    initial: function (item) { return typeof item.default === 'number' && isFinite(item.default) ? item.default : undefined; },
    coerce: function (item, raw) { return typeof raw === 'number' && isFinite(raw) && within(raw, item.min, item.max) ? raw : undefined; },
    answered: function () { return true; }
  });
  F.register('date', {
    make: date,
    initial: function (item) { return typeof item.default === 'string' && DAY.test(item.default) ? item.default : undefined; },
    coerce: function (item, raw) { return typeof raw === 'string' && DAY.test(raw) && within(raw, item.min, item.max) ? raw : undefined; },
    answered: function () { return true; }
  });
})();
