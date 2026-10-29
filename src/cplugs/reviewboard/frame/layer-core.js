/* <script */
(function () {
  'use strict';
  var STRING_PREFIX = 'cplug.reviewboard.layer.';
  var MAX_NOTE = 4000;
  var LAYER_VERSION = 1;
  var F = RbLayerFields;
  var el = F.el;

  var bridge = window.rb;
  var send = bridge && typeof bridge.send === 'function' ? bridge.send : null;
  if (bridge) bridge.send = function () {};

  var layer = null;
  var strings = {};
  var state = { values: {}, notes: {} };
  var cards = {};
  var mounted = [];
  var parts = null;

  function str(key) {
    var full = STRING_PREFIX + key;
    return typeof strings[full] === 'string' ? strings[full] : full;
  }

  function rowItems(data) {
    return data.rows.map(function (row) {
      return {
        id: row.id, kind: 'row', label: row.title, group: row.group, anchor: row.anchor, tag: row.tag, lines: row.lines, meta: row.meta,
        suggest: row.suggest, default: row.default, many: data.pick === 'several', options: row.choices || data.choices || []
      };
    });
  }

  function readLayer() {
    var block = document.getElementById('rb-layer');
    if (!block) return null;
    try {
      var data = JSON.parse(block.textContent || '');
      if (data && data.kind === 'rows' && Array.isArray(data.rows)) data.items = rowItems(data);
      return data && (data.kind === 'questions' || data.kind === 'rows') && Array.isArray(data.items) ? data : null;
    } catch (_) {
      return null;
    }
  }

  function defaults() {
    state = { values: {}, notes: {} };
    layer.items.forEach(function (item) {
      var v = F.initial(item);
      if (v !== undefined) state.values[item.id] = v;
    });
  }

  function adopt(payload) {
    if (!payload || payload.layer !== layer.kind || payload.v !== LAYER_VERSION || typeof payload.values !== 'object' || payload.values === null) return false;
    var saved = payload.notes && typeof payload.notes === 'object' ? payload.notes : {};
    state = { values: {}, notes: {} };
    layer.items.forEach(function (item) {
      var v = F.coerce(item, payload.values[item.id]);
      if (v === undefined && item.kind === 'toggle') v = false;
      if (v !== undefined) state.values[item.id] = v;
      var note = saved[item.id];
      if (typeof note === 'string' && note !== '' && note.length <= MAX_NOTE) state.notes[item.id] = note;
    });
    return true;
  }

  function post() {
    if (!send) return;
    var payload = { layer: layer.kind, v: LAYER_VERSION, values: state.values };
    if (Object.keys(state.notes).length) payload.notes = state.notes;
    send(JSON.parse(JSON.stringify(payload)));
  }

  function refreshCount() {
    if (!parts) return;
    var left = layer.items.filter(function (item) { return item.required && !F.answered(item, state.values[item.id]); }).length;
    parts.count.textContent = left ? left + ' ' + str('unanswered') : '';
    parts.count.hidden = left === 0;
  }

  function changed(item, value) {
    if (value === undefined) delete state.values[item.id]; else state.values[item.id] = value;
    refreshCount();
    post();
  }

  function noted(item, text) {
    if (text === '') delete state.notes[item.id]; else state.notes[item.id] = text;
    post();
  }

  function show(anchor) {
    window.dispatchEvent(new CustomEvent('rb-highlight', { detail: { anchor: anchor } }));
  }

  function anchorElement(id) {
    var list = document.querySelectorAll('[data-rb-anchor]');
    for (var i = 0; i < list.length; i++) if (list[i].getAttribute('data-rb-anchor') === id) return list[i];
    return null;
  }

  function key(text, cls) {
    var b = el('button', 'rbl-key ' + cls, text);
    b.type = 'button';
    return b;
  }

  function card(item) {
    var root = el('div', 'rbl-item');
    root.setAttribute('data-rbl-item', item.id);
    var head = el('div', 'rbl-head');
    head.appendChild(el('span', 'rbl-label', item.label));
    if (item.required) head.appendChild(el('span', 'rbl-req', '*'));
    head.appendChild(el('span', 'rbl-spacer'));
    if (layer.placement === 'float' && item.anchor) {
      var showKey = key(str('show'), 'rbl-show');
      showKey.addEventListener('click', function () { show(item.anchor); });
      head.appendChild(showKey);
    }
    var noteKey = key(str('note'), 'rbl-notekey');
    head.appendChild(noteKey);
    root.appendChild(head);
    if (item.help) root.appendChild(el('div', 'rbl-help', item.help));
    var control = F.make(item, state.values[item.id], { str: str, change: function (v) { changed(item, v); } });
    root.appendChild(control || el('div', 'rbl-help', str('unsupported')));
    var note = el('textarea', 'rbl-field rbl-note');
    note.rows = 2;
    note.maxLength = MAX_NOTE;
    note.placeholder = str('note_placeholder');
    note.value = state.notes[item.id] || '';
    note.hidden = note.value === '';
    function paintKey() {
      noteKey.setAttribute('aria-expanded', note.hidden ? 'false' : 'true');
      noteKey.classList.toggle('rbl-notekey--has', note.value !== '');
    }
    paintKey();
    noteKey.addEventListener('click', function () {
      note.hidden = !note.hidden;
      paintKey();
      if (!note.hidden) note.focus();
    });
    note.addEventListener('input', function () { noted(item, note.value); paintKey(); });
    root.appendChild(note);
    return root;
  }

  function header() {
    var head = el('header', 'rbl-strip');
    var title = el('div', 'rbl-title');
    title.appendChild(el('span', 'rbl-title__text', layer.title));
    var count = el('span', 'rbl-count');
    title.appendChild(count);
    head.appendChild(title);
    if (layer.intro) head.appendChild(el('p', 'rbl-intro', layer.intro));
    return { head: head, count: count };
  }

  function place() {
    if (!parts) return;
    parts.list.textContent = '';
    var lastAfter = {};
    var group = null;
    layer.items.forEach(function (item) {
      var node = cards[item.id];
      var part = layer.placement === 'inline' && item.anchor ? anchorElement(item.anchor) : null;
      node.classList.toggle('rbl-item--inline', part !== null);
      if (part) {
        (lastAfter[item.anchor] || part).after(node);
        lastAfter[item.anchor] = node;
        return;
      }
      if (item.group !== group) {
        group = item.group || null;
        if (group) parts.list.appendChild(el('div', 'rbl-group', group));
      }
      parts.list.appendChild(node);
    });
  }

  function unmount() {
    mounted.forEach(function (node) { node.remove(); });
    mounted = [];
    Object.keys(cards).forEach(function (id) { cards[id].remove(); });
    cards = {};
    parts = null;
  }

  function build() {
    if (!layer) return;
    unmount();
    var top = header();
    var list = el('div', 'rbl-list');
    parts = { list: list, count: top.count };
    layer.items.forEach(function (item) { cards[item.id] = card(item); });
    var shell = layer.placement === 'float' ? el('aside', 'rbl rbl-float') : el('section', 'rbl rbl-end');
    shell.appendChild(top.head);
    shell.appendChild(list);
    if (layer.placement === 'float') {
      var fold = key(layer.title, 'rbl-fold');
      fold.setAttribute('aria-expanded', 'true');
      fold.addEventListener('click', function () {
        var open = shell.classList.toggle('rbl-float--closed') === false;
        fold.setAttribute('aria-expanded', open ? 'true' : 'false');
      });
      shell.insertBefore(fold, top.head);
      document.body.appendChild(shell);
    } else {
      (document.querySelector('[data-rb-layer-root]') || document.body).appendChild(shell);
    }
    mounted.push(shell);
    place();
    refreshCount();
  }

  window.addEventListener('rb-strings', function (event) {
    var map = event.detail && event.detail.map;
    if (!map || typeof map !== 'object') return;
    strings = map;
    build();
  });
  window.addEventListener('rb-load', function (event) {
    if (!layer) return;
    var detail = event.detail;
    if (detail && adopt(detail.payload)) build();
  });

  function start() {
    layer = readLayer();
    if (!layer) return;
    defaults();
    build();
    window.addEventListener('load', place);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
