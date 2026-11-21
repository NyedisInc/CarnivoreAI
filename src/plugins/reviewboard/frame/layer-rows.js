(function () {
  'use strict';
  var F = RbLayerFields;
  var el = F.el;
  var TONES = { ok: true, push: true, later: true, none: true };

  function fit(item, raw) {
    var ids = F.optionIds(item);
    if (item.many) {
      if (!Array.isArray(raw)) return undefined;
      var kept = ids.filter(function (id) { return raw.indexOf(id) >= 0; });
      return kept.length ? kept : undefined;
    }
    return typeof raw === 'string' && ids.indexOf(raw) >= 0 ? raw : undefined;
  }

  function lines(list) {
    var box = el('div', 'rbl-lines');
    list.forEach(function (line) {
      var row = el('div', 'rbl-line');
      row.appendChild(el('b', 'rbl-line__label', line.label));
      row.appendChild(document.createTextNode(' '));
      row.appendChild(el('span', 'rbl-line__text', line.text));
      box.appendChild(row);
    });
    return box;
  }

  function picks(item, value, api) {
    var group = el('div', 'rbl-opts rbl-picks');
    group.setAttribute('role', 'group');
    var chosen = item.many ? (Array.isArray(value) ? value.slice() : []) : (typeof value === 'string' ? [value] : []);
    var buttons = [];
    function refresh() {
      buttons.forEach(function (b, i) { b.setAttribute('aria-pressed', chosen.indexOf(item.options[i].id) >= 0 ? 'true' : 'false'); });
    }
    (item.options || []).forEach(function (o) {
      var b = el('button', 'rbl-opt rbl-tone-' + (TONES[o.tone] ? o.tone : 'none'));
      b.type = 'button';
      b.appendChild(el('span', 'rbl-opt__text', o.label));
      if (item.suggest === o.id) {
        b.setAttribute('data-rbl-suggest', 'true');
        b.appendChild(el('span', 'rbl-opt__mark', api.str('suggested')));
      }
      b.addEventListener('click', function () {
        var at = chosen.indexOf(o.id);
        if (item.many) { if (at >= 0) chosen.splice(at, 1); else chosen.push(o.id); } else chosen = at >= 0 ? [] : [o.id];
        refresh();
        var ordered = F.optionIds(item).filter(function (id) { return chosen.indexOf(id) >= 0; });
        api.change(ordered.length ? (item.many ? ordered : ordered[0]) : undefined);
      });
      buttons.push(b);
      group.appendChild(b);
    });
    refresh();
    return group;
  }

  function row(item, value, api) {
    var root = el('div', 'rbl-row');
    if (item.tag) root.appendChild(el('span', 'rbl-chip', item.tag));
    if (item.lines && item.lines.length) root.appendChild(lines(item.lines));
    if (item.meta) root.appendChild(el('div', 'rbl-meta', item.meta));
    root.appendChild(picks(item, value, api));
    return root;
  }

  F.register('row', {
    make: row,
    initial: function (item) { return fit(item, item.default); },
    coerce: fit,
    answered: function () { return true; }
  });
})();
