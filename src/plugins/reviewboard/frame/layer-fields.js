var RbLayerFields = (function () {
  'use strict';
  var SHORT_MAX = 300;
  var LONG_MAX = 4000;
  var LONG_ROWS = 4;

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function pick(label, on) {
    var b = el('button', 'rbl-opt', label);
    b.type = 'button';
    b.setAttribute('aria-pressed', on ? 'true' : 'false');
    return b;
  }

  function paint(button, on) {
    button.setAttribute('aria-pressed', on ? 'true' : 'false');
  }

  function optionIds(item) {
    return (item.options || []).map(function (o) { return o.id; });
  }

  function yesno(item, value, api) {
    var group = el('div', 'rbl-opts');
    group.setAttribute('role', 'group');
    var yes = pick(api.str('yes'), value === true);
    var no = pick(api.str('no'), value === false);
    function set(next) {
      paint(yes, next === true);
      paint(no, next === false);
      api.change(next);
    }
    yes.addEventListener('click', function () { set(yes.getAttribute('aria-pressed') === 'true' ? undefined : true); });
    no.addEventListener('click', function () { set(no.getAttribute('aria-pressed') === 'true' ? undefined : false); });
    group.appendChild(yes);
    group.appendChild(no);
    return group;
  }

  function choice(item, value, api) {
    var group = el('div', 'rbl-opts');
    group.setAttribute('role', 'group');
    var buttons = (item.options || []).map(function (o) {
      var b = pick(o.label, value === o.id);
      b.addEventListener('click', function () {
        buttons.forEach(function (other, i) { paint(other, item.options[i].id === o.id); });
        api.change(o.id);
      });
      group.appendChild(b);
      return b;
    });
    return group;
  }

  function multi(item, value, api) {
    var group = el('div', 'rbl-opts');
    group.setAttribute('role', 'group');
    var chosen = Array.isArray(value) ? value.slice() : [];
    var buttons = [];
    function refresh() {
      buttons.forEach(function (b, i) {
        var on = chosen.indexOf(item.options[i].id) >= 0;
        paint(b, on);
        b.disabled = !on && item.max != null && chosen.length >= item.max;
      });
    }
    (item.options || []).forEach(function (o) {
      var b = pick(o.label, false);
      b.addEventListener('click', function () {
        var at = chosen.indexOf(o.id);
        if (at >= 0) chosen.splice(at, 1);
        else if (item.max == null || chosen.length < item.max) chosen.push(o.id);
        refresh();
        api.change(chosen.length ? optionIds(item).filter(function (id) { return chosen.indexOf(id) >= 0; }) : undefined);
      });
      buttons.push(b);
      group.appendChild(b);
    });
    refresh();
    return group;
  }

  function toggle(item, value, api) {
    var b = el('button', 'rbl-switch');
    b.type = 'button';
    b.setAttribute('role', 'switch');
    var knob = el('span', 'rbl-switch__knob');
    var word = el('span', 'rbl-switch__word');
    b.appendChild(knob);
    b.appendChild(word);
    function paintSwitch(on) {
      b.setAttribute('aria-checked', on ? 'true' : 'false');
      word.textContent = api.str(on ? 'on' : 'off');
    }
    paintSwitch(value === true);
    b.addEventListener('click', function () {
      var next = b.getAttribute('aria-checked') !== 'true';
      paintSwitch(next);
      api.change(next);
    });
    return b;
  }

  function text(item, value, api) {
    var long = item.kind === 'longtext';
    var field = el(long ? 'textarea' : 'input', 'rbl-field');
    if (long) field.rows = LONG_ROWS; else field.type = 'text';
    field.maxLength = long ? LONG_MAX : SHORT_MAX;
    if (item.placeholder) field.placeholder = item.placeholder;
    field.value = typeof value === 'string' ? value : '';
    field.addEventListener('input', function () { api.change(field.value === '' ? undefined : field.value); });
    return field;
  }

  var MAKERS = { yesno: yesno, choice: choice, multi: multi, toggle: toggle, text: text, longtext: text };
  var EXTRA = {};

  function register(kind, spec) {
    EXTRA[kind] = spec;
  }

  function isText(raw, limit) {
    return typeof raw === 'string' && raw.length <= limit;
  }

  function initial(item) {
    if (EXTRA[item.kind]) return EXTRA[item.kind].initial(item);
    if (item.kind === 'toggle') return item.default === true;
    if (item.kind === 'yesno' || MAKERS[item.kind] === undefined) return undefined;
    var d = item.default;
    if (item.kind === 'multi') return Array.isArray(d) && d.length ? d.slice() : undefined;
    return d === undefined || d === '' ? undefined : d;
  }

  function coerce(item, raw) {
    if (raw === undefined || raw === null) return undefined;
    if (EXTRA[item.kind]) return EXTRA[item.kind].coerce(item, raw);
    switch (item.kind) {
      case 'yesno':
      case 'toggle':
        return typeof raw === 'boolean' ? raw : undefined;
      case 'choice':
        return typeof raw === 'string' && optionIds(item).indexOf(raw) >= 0 ? raw : undefined;
      case 'multi': {
        if (!Array.isArray(raw)) return undefined;
        var ids = optionIds(item);
        var kept = ids.filter(function (id) { return raw.indexOf(id) >= 0; });
        return kept.length && (item.max == null || kept.length <= item.max) ? kept : undefined;
      }
      case 'text':
        return isText(raw, SHORT_MAX) && raw !== '' ? raw : undefined;
      case 'longtext':
        return isText(raw, LONG_MAX) && raw !== '' ? raw : undefined;
      default:
        return raw;
    }
  }

  function answered(item, value) {
    if (value === undefined) return false;
    if (EXTRA[item.kind]) return EXTRA[item.kind].answered(item, value);
    if (item.kind === 'multi') return value.length >= Math.max(1, item.min || 0);
    return true;
  }

  function make(item, value, api) {
    var maker = MAKERS[item.kind] || (EXTRA[item.kind] && EXTRA[item.kind].make);
    return maker ? maker(item, value, api) : null;
  }

  return { make: make, initial: initial, coerce: coerce, answered: answered, register: register, el: el, optionIds: optionIds };
})();
