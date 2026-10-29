(function () {
    'use strict';

    var CACHE_KEY = 'cloude.dev.perf_hooks';
    var RATE_WINDOW_MS = 5000;
    var ECHO_SAMPLES = 50;

    var state = null;
    var pollerSources = [];
    var serverSample = null;
    var listeners = [];

    function cachedOn() {
        try { return window.localStorage.getItem(CACHE_KEY) === '1'; } catch (e) { return false; }
    }

    function remember(on) {
        try {
            if (on) window.localStorage.setItem(CACHE_KEY, '1');
            else window.localStorage.removeItem(CACHE_KEY);
        } catch (e) {  }
    }

    function trim(list, now) {
        while (list.length && now - list[0][0] > RATE_WINDOW_MS) list.shift();
    }

    function callerLabel() {
        var stack = (new Error().stack || '').split('\n');
        for (var i = 1; i < stack.length; i += 1) {
            if (stack[i].indexOf('perf-probe.js') === -1 && /https?:/.test(stack[i])) {
                return stack[i].replace(/^\s*at\s*/, '').replace(/\?v=[0-9a-f]+/, '').slice(0, 160);
            }
        }
        return 'unknown';
    }

    function onSocketMessage(socket, event) {
        var now = performance.now();
        var data = event.data;
        var size = typeof data === 'string' ? data.length : (data && (data.byteLength || data.size)) || 0;
        var path = socket.__perfPath;
        var rx = state.rx[path] || (state.rx[path] = []);
        rx.push([now, size]);
        trim(rx, now);
        if (typeof data !== 'string' && socket.__perfSentAt !== undefined) {
            var sent = socket.__perfSentAt;
            socket.__perfSentAt = undefined;
            var net = now - sent;
            window.requestAnimationFrame(function () {
                state.echo.push({ net: net, painted: performance.now() - sent });
                if (state.echo.length > ECHO_SAMPLES) state.echo.shift();
            });
        }
    }

    function install() {
        if (state) return;
        state = {
            rx: {}, echo: [], frames: [], intervals: new Map(),
            orig: {
                WebSocket: window.WebSocket, setInterval: window.setInterval,
                clearInterval: window.clearInterval, raf: window.requestAnimationFrame,
            },
        };
        var orig = state.orig;
        var Base = orig.WebSocket;
        function ProbedSocket(url, protocols) {
            var socket = protocols === undefined ? new Base(url) : new Base(url, protocols);
            try { socket.__perfPath = new URL(url, window.location.href).pathname; } catch (e) { socket.__perfPath = String(url); }
            socket.addEventListener('message', function (event) { if (state) onSocketMessage(socket, event); });
            var send = socket.send;
            socket.send = function (data) {
                if (state && typeof data !== 'string' && socket.__perfPath.indexOf('/ws/terminal') !== -1
                        && socket.__perfSentAt === undefined) {
                    socket.__perfSentAt = performance.now();
                }
                return send.call(socket, data);
            };
            return socket;
        }
        ProbedSocket.prototype = Base.prototype;
        ['CONNECTING', 'OPEN', 'CLOSING', 'CLOSED'].forEach(function (k) { ProbedSocket[k] = Base[k]; });
        window.WebSocket = ProbedSocket;

        window.setInterval = function (handler, ms) {
            var id = orig.setInterval.apply(window, arguments);
            if (state) state.intervals.set(id, { ms: Number(ms) || 0, where: callerLabel() });
            return id;
        };
        window.clearInterval = function (id) {
            if (state) state.intervals.delete(id);
            return orig.clearInterval.call(window, id);
        };
        window.requestAnimationFrame = function (cb) {
            if (state) {
                var now = performance.now();
                state.frames.push([now, 0]);
                trim(state.frames, now);
            }
            return orig.raf.call(window, cb);
        };
    }

    function uninstall() {
        if (!state) return;
        window.WebSocket = state.orig.WebSocket;
        window.setInterval = state.orig.setInterval;
        window.clearInterval = state.orig.clearInterval;
        window.requestAnimationFrame = state.orig.raf;
        state = null;
        serverSample = null;
    }

    function median(list) {
        if (!list.length) return null;
        var sorted = list.slice().sort(function (a, b) { return a - b; });
        return sorted[Math.floor(sorted.length / 2)];
    }

    function snapshot() {
        if (!state) return null;
        var now = performance.now();
        var seconds = RATE_WINDOW_MS / 1000;
        var rx = Object.keys(state.rx).map(function (path) {
            var list = state.rx[path];
            trim(list, now);
            var bytes = list.reduce(function (sum, item) { return sum + item[1]; }, 0);
            return { path: path, msgs_per_s: list.length / seconds, bytes_per_s: bytes / seconds };
        });
        trim(state.frames, now);
        var pollers = [];
        state.intervals.forEach(function (info) {
            pollers.push({ kind: 'interval', name: info.where, ms: info.ms, where: info.where });
        });
        pollerSources.forEach(function (source) {
            try {
                source().forEach(function (p) { pollers.push({ kind: 'resource', name: p.name, ms: p.intervalMs, where: p.name }); });
            } catch (e) {  }
        });
        pollers.sort(function (a, b) { return a.ms - b.ms; });
        return {
            echo: {
                net_ms: median(state.echo.map(function (s) { return s.net; })),
                painted_ms: median(state.echo.map(function (s) { return s.painted; })),
                worst_ms: state.echo.length ? Math.max.apply(null, state.echo.map(function (s) { return s.painted; })) : null,
                samples: state.echo.length,
            },
            rx: rx,
            frames_per_s: state.frames.length / seconds,
            pollers: pollers,
            server: serverSample,
        };
    }

    window.PerfProbe = {
        install: install,
        uninstall: uninstall,
        isInstalled: function () { return state !== null; },
        snapshot: snapshot,
        remember: remember,
        registerPollerSource: function (fn) { if (typeof fn === 'function') pollerSources.push(fn); },
        acceptServerSample: function (frame) {
            if (!state) return;
            serverSample = frame;
            listeners.forEach(function (fn) { try { fn(frame); } catch (e) {  } });
        },
        onServerSample: function (fn) {
            listeners.push(fn);
            return function () { listeners = listeners.filter(function (f) { return f !== fn; }); };
        },
    };

    if (cachedOn()) install();
})();
