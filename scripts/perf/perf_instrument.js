(function () {
  if (window.__perfInstrumented) return;
  window.__perfInstrumented = true;
  window.__wsLog = [];
  window.__renderLog = [];

  document.addEventListener('keydown', () => { window.__keyDispatchAt = performance.now(); }, true);
  document.addEventListener('click', () => {
    if (window.__switchTarget && !window.__switchTarget.dispatchAt) window.__switchTarget.dispatchAt = performance.now();
  }, true);
  const NativeWebSocket = window.WebSocket;
  function PerfWebSocket(url, protocols) {
    const sock = protocols === undefined
      ? new NativeWebSocket(url)
      : new NativeWebSocket(url, protocols);
    const tag = String(url);
    window.__wsLog.push({t:performance.now(),dir:'construct',url:tag});
    sock.addEventListener('open',()=>window.__wsLog.push({t:performance.now(),dir:'open',url:tag}));
    sock.addEventListener('message', function (ev) {
      const entry = { t: performance.now(), dir: 'recv', url: tag, size: 0, preview: '', binary: typeof ev.data !== 'string' };
      window.__wsLog.push(entry);
      if (typeof ev.data === 'string') {
        entry.size = ev.data.length;
        entry.preview = ev.data.slice(0, 120);
        try { const msg = JSON.parse(ev.data); if (msg.type === 'terminal.ready') entry.ready = true; } catch (_) {}
      } else if (ev.data && typeof ev.data.size === 'number') {
        entry.size = ev.data.size;
        if (typeof ev.data.text === 'function') {
          ev.data.text().then(function (t) { entry.preview = t.slice(0, 120); });
        }
      } else if (ev.data instanceof ArrayBuffer) {
        entry.size = ev.data.byteLength;
        entry.preview = new TextDecoder().decode(ev.data).slice(0, 120);
      }
    });
    const nativeSend = sock.send.bind(sock);
    sock.send = function (data) {
      let size = 0;
      let preview = '';
      if (typeof data === 'string') { size = data.length; preview = data.slice(0, 120); }
      else if (data instanceof ArrayBuffer) { size = data.byteLength; preview = new TextDecoder().decode(data).slice(0, 120); }
      else if (data && typeof data.byteLength === 'number') { size = data.byteLength; }
      window.__wsLog.push({ t: performance.now(), dir: 'send', url: tag, size: size, preview: preview });
      return nativeSend(data);
    };
    return sock;
  }
  PerfWebSocket.prototype = NativeWebSocket.prototype;
  PerfWebSocket.CONNECTING = NativeWebSocket.CONNECTING;
  PerfWebSocket.OPEN = NativeWebSocket.OPEN;
  PerfWebSocket.CLOSING = NativeWebSocket.CLOSING;
  PerfWebSocket.CLOSED = NativeWebSocket.CLOSED;
  window.WebSocket = PerfWebSocket;

  window.__armRenderHook = function () {
    const term = window.TerminalController && window.TerminalController.term;
    if (!term || term.__perfHooked) return !!term;
    term.__perfHooked = true;
    term.onRender(function () {
      let text = '';
      try {
        const buf = term.buffer.active;
        const rows = [];
        for (let i = 0; i < term.rows; i++) {
          const line = buf.getLine(buf.viewportY + i);
          rows.push(line ? line.translateToString(true) : '');
        }
        text = rows.join('\n');
      } catch (e) {
        text = '';
      }
      window.__renderLog.push({ t: performance.now(), text: text, sessionId: window.TerminalController._sessionId() });
    });
    return true;
  };

  window.__nonBlankRendered = function () {
    return window.__renderLog.some(function (r) { return r.text && r.text.trim().length > 0; });
  };

  window.__armSwitch = function (sessionId, marker) {
    window.__armRenderHook();
    window.__switchTarget = {sessionId, marker, startedAt: window.__armEcho()};
    return window.__switchTarget.startedAt;
  };
  window.__switchSnapshot = function () {
    window.__armRenderHook();
    const target = window.__switchTarget;
    if (!target) return null;
    const ready = window.__wsLog.find(w => w.ready && new URL(w.url).searchParams.get('session_id') === target.sessionId);
    const bytes = window.__wsLog.find(w => w.binary && new URL(w.url).searchParams.get('session_id') === target.sessionId);
    const paint = bytes && window.__renderLog.find(r => r.t >= bytes.t && r.sessionId === target.sessionId && (target.marker ? r.text.includes(target.marker) : r.text.trim().length > 0));
    return ready && paint ? {readyAt: ready.t, paintAt: paint.t, doneAt: Math.max(ready.t, paint.t), dispatchAt:target.dispatchAt} : null;
  };

  window.__armEcho = function () {
    window.__wsLog = [];
    window.__renderLog = [];
    return performance.now();
  };

  window.__echoSnapshot = function (needle) {
    const hit = window.__renderLog.find(function (r) { return needle === '' || r.text.indexOf(needle) !== -1; });
    const sid = window.TerminalController && window.TerminalController._sessionId();
    const ownSocket = w => new URL(w.url).searchParams.get('session_id') === sid;
    const sends = window.__wsLog.filter(w => w.dir === 'send' && ownSocket(w));
    const recvs = window.__wsLog.filter(w => w.dir === 'recv' && w.binary && ownSocket(w));
    return {
      dispatchAt: window.__keyDispatchAt,
      rendered: !!hit,
      renderAt: hit ? hit.t : null,
      sentAt: sends.length ? sends[0].t : null,
      recvAt: recvs.length ? recvs[0].t : null,
    };
  };

  window.__visibleBox = function (selector) {
    const el = document.querySelector(selector);
    if (!el) return null;
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    const onScreen = rect.right > 0 && rect.left < (window.innerWidth || 0)
      && rect.bottom > 0 && rect.top < (window.innerHeight || 0);
    const visible = rect.width > 0 && rect.height > 0 && onScreen
      && style.visibility !== 'hidden' && style.display !== 'none'
      && parseFloat(style.opacity || '1') > 0.01;
    return { visible: visible, width: rect.width, height: rect.height, t: performance.now() };
  };
})();
