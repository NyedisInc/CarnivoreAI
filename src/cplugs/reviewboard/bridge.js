(function () {
  'use strict';
  var VERSION = 1;
  var MAX_BYTES = 4096;
  var MAX_LOAD_BYTES = 64 * 1024 + 2048;
  var MAX_THEME_BYTES = 48 * 1024;
  var SEND_GAP_MS = 100;
  var MAX_ID = 64;
  var HIGHLIGHT_MS = 2000;
  var HIGHLIGHT_ATTR = 'data-rb-highlight';
  var STRING_KEY = /^cplug\.reviewboard\.layer\.[a-z0-9_]{1,40}$/;
  var MAX_STRING = 300;
  var NAME = /^--[a-z0-9-]{1,64}$/;
  var ANCHOR = /^[a-z][a-z0-9_-]{0,31}$/;
  var THEME_ID = /^[A-Za-z0-9._-]{1,64}$/;
  var MAX_VARS = 600;
  var MAX_VALUE = 200;
  var highlightTimer = 0;
  var GAP_ATTR = 'data-rb-gap';
  var MAX_GAP_PX = 1200;
  var LAYOUT_GAP_MS = 100;
  var wantedGaps = {};
  var layoutTimer = 0;
  var SCROLLBAR_ATTR = 'data-rb-scrollbar';
  var SCROLLBAR_CSS = '@media (hover: hover) and (pointer: fine) {' +
    ':root { --scrollbar-size: 11px; --scrollbar-inset: 2px; --scrollbar-thumb-min: 36px; }' +
    '::-webkit-scrollbar { width: var(--scrollbar-size); height: var(--scrollbar-size); }' +
    '::-webkit-scrollbar-track, ::-webkit-scrollbar-corner { background-color: var(--oc-ground-page, transparent); }' +
    '::-webkit-scrollbar-thumb { background-color: var(--oc-scrollbar-thumb-rest, color-mix(in oklab, currentColor 40%, transparent));' +
    ' background-clip: padding-box; border: var(--scrollbar-inset) solid transparent; border-radius: var(--scrollbar-size);' +
    ' min-height: var(--scrollbar-thumb-min); min-width: var(--scrollbar-thumb-min); }' +
    '::-webkit-scrollbar-track:hover { background-color: var(--oc-scrollbar-track, var(--oc-ground-page, transparent)); }' +
    '::-webkit-scrollbar-thumb:hover { background-color: var(--oc-scrollbar-thumb-hover, color-mix(in oklab, currentColor 60%, transparent)); }' +
    '::-webkit-scrollbar-thumb:active { background-color: var(--oc-scrollbar-thumb-active, currentColor); }' +
    '@supports not selector(::-webkit-scrollbar) { :root { scrollbar-width: thin; scrollbar-color: var(--oc-scrollbar-thumb-rest, currentColor) transparent; } }' +
    '}';
  var pendingPayload = null;
  var sendTimer = 0;

  function safeValue(value) {
    if (typeof value !== 'string' || value.length === 0 || value.length > MAX_VALUE) return false;
    if (/[<>{};\\]/.test(value) || /[\u0000-\u001f]/.test(value)) return false;
    if (/@import|expression\(|javascript:/i.test(value)) return false;
    var urls = value.match(/url\(\s*['"]?([^)'"]*)/gi) || [];
    for (var i = 0; i < urls.length; i++) {
      if (!/^url\(\s*['"]?data:/i.test(urls[i])) return false;
    }
    return true;
  }

  function post(type, fields) {
    if (window.parent === window) return;
    var message = { rb: VERSION, type: type };
    for (var key in fields) message[key] = fields[key];
    window.parent.postMessage(message, '*');
  }

  function element(id) {
    if (typeof id !== 'string' || !ANCHOR.test(id)) return null;
    var list = document.querySelectorAll('[data-rb-anchor]');
    for (var i = 0; i < list.length; i++) if (list[i].getAttribute('data-rb-anchor') === id) return list[i];
    return null;
  }

  function anchorIds() {
    var ids = [];
    var list = document.querySelectorAll('[data-rb-anchor]');
    for (var i = 0; i < list.length && ids.length < 60; i++) {
      var id = list[i].getAttribute('data-rb-anchor');
      if (ANCHOR.test(id) && ids.indexOf(id) < 0) ids.push(id);
    }
    return ids;
  }

  function themeAware() {
    var pattern = /var\(\s*--(oc|color)-/;
    var sheets = document.querySelectorAll('style:not([' + SCROLLBAR_ATTR + '])');
    for (var i = 0; i < sheets.length; i++) if (pattern.test(sheets[i].textContent || '')) return true;
    var inline = document.querySelectorAll('[style]');
    for (var j = 0; j < inline.length; j++) if (pattern.test(inline[j].getAttribute('style') || '')) return true;
    return false;
  }

  function onTheme(message) {
    if (typeof message.id !== 'string' || !THEME_ID.test(message.id) || !message.vars || typeof message.vars !== 'object') return;
    var root = document.documentElement;
    var names = Object.keys(message.vars).slice(0, MAX_VARS);
    for (var i = 0; i < names.length; i++) {
      var name = names[i];
      if (NAME.test(name) && safeValue(message.vars[name])) root.style.setProperty(name, message.vars[name]);
    }
    root.setAttribute('data-theme-id', message.id);
  }

  function mark(attribute, ids) {
    var wanted = Array.isArray(ids) ? ids.slice(0, 60) : [];
    var list = document.querySelectorAll('[data-rb-anchor]');
    for (var i = 0; i < list.length; i++) {
      var id = list[i].getAttribute('data-rb-anchor');
      if (wanted.indexOf(id) >= 0) list[i].setAttribute(attribute, ''); else list[i].removeAttribute(attribute);
    }
  }

  function onHighlight(message) {
    var target = element(message.anchor);
    if (!target) return;
    var old = document.querySelector('[' + HIGHLIGHT_ATTR + ']');
    if (old) old.removeAttribute(HIGHLIGHT_ATTR);
    target.setAttribute(HIGHLIGHT_ATTR, '');
    target.style.setProperty('outline', '2px solid currentColor');
    target.style.setProperty('outline-offset', '2px');
    if (target.scrollIntoView) target.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    clearTimeout(highlightTimer);
    highlightTimer = setTimeout(function () {
      target.removeAttribute(HIGHLIGHT_ATTR);
      target.style.removeProperty('outline');
      target.style.removeProperty('outline-offset');
    }, HIGHLIGHT_MS);
  }

  function spacerOf(id) {
    var list = document.querySelectorAll('[' + GAP_ATTR + ']');
    for (var i = 0; i < list.length; i++) if (list[i].getAttribute(GAP_ATTR) === id) return list[i];
    return null;
  }

  function sizeSpacer(spacer, px) {
    var box = spacer.tagName === 'TR' && spacer.firstChild ? spacer.firstChild : spacer;
    box.style.setProperty('height', px + 'px');
  }

  function makeSpacer(anchor, id) {
    var tag = anchor.tagName;
    var spacer = document.createElement(tag === 'TR' ? 'tr' : tag === 'LI' ? 'li' : 'div');
    spacer.setAttribute(GAP_ATTR, id);
    spacer.setAttribute('aria-hidden', 'true');
    if (tag === 'TR') {
      var cell = document.createElement('td');
      cell.colSpan = 99;
      cell.style.cssText = 'padding:0;border:0;visibility:hidden';
      spacer.appendChild(cell);
    } else {
      spacer.style.cssText = 'display:block;box-sizing:border-box;margin:0;padding:0;border:0;list-style:none;flex:none;width:100%;clear:both;pointer-events:none;visibility:hidden';
    }
    return spacer;
  }

  function postLayout() {
    var gaps = {};
    Object.keys(wantedGaps).forEach(function (id) {
      var spacer = spacerOf(id);
      if (!spacer) return;
      var rect = spacer.getBoundingClientRect();
      gaps[id] = [Math.round(rect.left), Math.round(rect.top), Math.round(rect.width)];
    });
    post('layout', { gaps: gaps, h: Math.round(window.innerHeight || 0) });
  }

  function scheduleLayout() {
    if (layoutTimer || Object.keys(wantedGaps).length === 0) return;
    layoutTimer = setTimeout(function () {
      layoutTimer = 0;
      postLayout();
    }, LAYOUT_GAP_MS);
  }

  function onGaps(message) {
    var map = message.gaps;
    if (!map || typeof map !== 'object' || Array.isArray(map)) return;
    var clean = {};
    Object.keys(map).slice(0, 60).forEach(function (id) {
      var px = map[id];
      if (ANCHOR.test(id) && typeof px === 'number' && isFinite(px) && px >= 0 && px <= MAX_GAP_PX) clean[id] = Math.round(px);
    });
    wantedGaps = clean;
    var placed = document.querySelectorAll('[' + GAP_ATTR + ']');
    for (var i = 0; i < placed.length; i++) if (!(placed[i].getAttribute(GAP_ATTR) in clean)) placed[i].remove();
    Object.keys(clean).forEach(function (id) {
      var anchor = element(id);
      if (!anchor || !anchor.parentNode) return;
      var spacer = spacerOf(id);
      if (!spacer) {
        spacer = makeSpacer(anchor, id);
        anchor.parentNode.insertBefore(spacer, anchor.nextSibling);
      }
      sizeSpacer(spacer, clean[id]);
    });
    scheduleLayout();
  }

  function onStrings(message) {
    var map = message.map;
    if (!map || typeof map !== 'object' || Array.isArray(map)) return;
    var clean = {};
    Object.keys(map).forEach(function (name) {
      if (STRING_KEY.test(name) && typeof map[name] === 'string' && map[name].length <= MAX_STRING) clean[name] = map[name];
    });
    window.dispatchEvent(new CustomEvent('rb-strings', { detail: { map: clean } }));
  }

  function onLoad(message) {
    var payload = message.payload;
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return;
    var save = typeof message.save === 'number' ? message.save : null;
    window.dispatchEvent(new CustomEvent('rb-load', { detail: { payload: payload, save: save } }));
  }

  function sendPayload(payload) {
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return;
    pendingPayload = payload;
    if (sendTimer) return;
    sendTimer = setTimeout(function () {
      sendTimer = 0;
      var next = pendingPayload;
      pendingPayload = null;
      if (next) post('payload', { payload: next });
    }, SEND_GAP_MS);
  }
  window.rb = { send: sendPayload };

  function installScrollbarSkin() {
    var style = document.createElement('style');
    style.setAttribute(SCROLLBAR_ATTR, '');
    style.textContent = SCROLLBAR_CSS;
    var host = document.head || document.documentElement;
    host.insertBefore(style, host.firstChild);
  }
  installScrollbarSkin();

  window.addEventListener('message', function (event) {
    if (event.source !== window.parent || window.parent === window) return;
    var data = event.data;
    if (!data || typeof data !== 'object' || data.rb !== VERSION || typeof data.type !== 'string') return;
    try {
      if (JSON.stringify(data).length > (data.type === 'load' ? MAX_LOAD_BYTES : data.type === 'theme' ? MAX_THEME_BYTES : MAX_BYTES)) return;
    } catch (_) {
      return;
    }
    if (data.type === 'theme') onTheme(data);
    else if (data.type === 'state') { mark('data-rb-answered', data.answered_anchors); mark('data-rb-noted', data.noted_anchors); }
    else if (data.type === 'highlight') onHighlight(data);
    else if (data.type === 'load') onLoad(data);
    else if (data.type === 'strings') onStrings(data);
    else if (data.type === 'gaps') onGaps(data);
  });

  window.addEventListener('scroll', scheduleLayout, true);
  window.addEventListener('resize', scheduleLayout);
  if (window.ResizeObserver && document.documentElement) new window.ResizeObserver(scheduleLayout).observe(document.documentElement);

  window.addEventListener('rb-highlight', function (event) {
    if (event.detail) onHighlight({ anchor: event.detail.anchor });
  });

  document.addEventListener('click', function (event) {
    var node = event.target;
    var tagged = node && node.closest ? node.closest('[data-rb-anchor]') : null;
    if (!tagged) return;
    var id = tagged.getAttribute('data-rb-anchor');
    if (typeof id === 'string' && id.length <= MAX_ID && ANCHOR.test(id)) post('anchor', { anchor: id });
  }, true);

  function ready() { post('ready', { anchors: anchorIds(), theme_aware: themeAware() }); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready); else ready();
})();
