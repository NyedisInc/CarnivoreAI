'use strict';

function safePath(p) {
  if (typeof p !== 'string' || p.charAt(0) !== '/') return null;
  if (p.charAt(1) === '/' || p.charAt(1) === '\\') return null;
  if (/[\u0000-\u001f\u007f\\]/.test(p)) return null;
  try {
    if (new URL(p, self.location.origin).origin !== self.location.origin) return null;
  } catch (_err) {
    return null;
  }
  return p;
}

function readPayload(event) {
  let data = null;
  try {
    data = event.data ? event.data.json() : null;
  } catch (_err) {
    data = null;
  }
  const obj = data && typeof data === 'object' ? data : {};
  const str = (v) => (typeof v === 'string' && v.trim() ? v : null);
  const title = str(obj.title);
  const text = str(obj.body);
  return {
    title: title || 'carnivore',
    body: text || 'approval needed',
    path: safePath(obj.path),
    typed: Boolean(title || text),
  };
}

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

self.addEventListener('push', (event) => {
  const p = readPayload(event);
  const options = { body: p.body, icon: '/apple-touch-icon.png', data: { path: p.path } };
  if (!p.typed) {
    options.tag = 'approval';
    options.renotify = true;
  }
  event.waitUntil(self.registration.showNotification(p.title, options));
});

function askSession(target) {
  try {
    const url = new URL(target, self.location.origin);
    return url.pathname === '/' ? url.searchParams.get('approvals') || null : null;
  } catch (_err) {
    return null;
  }
}

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = safePath(event.notification.data && event.notification.data.path) || '/';
  const ask = askSession(target);
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windows) => {
      const open = windows.find((w) => 'focus' in w);
      if (!open) return self.clients.openWindow(target);
      return open.focus().then((c) => {
        const win = c || open;
        if (ask && 'postMessage' in win) {
          win.postMessage({ type: 'carnivore.open-approval', session_id: ask });
          return undefined;
        }
        return 'navigate' in win ? win.navigate(target) : self.clients.openWindow(target);
      });
    })
  );
});
