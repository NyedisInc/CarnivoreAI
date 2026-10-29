(function () {
    'use strict';

    var MAX_INSET = 200;

    var bridge = typeof window !== 'undefined' ? window.carnivoreDesktop : undefined;
    var caps = bridge && bridge.capabilities;
    if (!bridge || !caps || typeof caps.indexOf !== 'function' || caps.indexOf('windowChrome') < 0 || typeof bridge.windowChrome !== 'function') return;

    var root = document.documentElement;
    root.dataset.desktopChrome = '';

    function okInset(n) {
        return typeof n === 'number' && isFinite(n) && n >= 0 && n <= MAX_INSET;
    }

    function apply(state) {
        if (!state || !state.inset || !okInset(state.inset.top) || !okInset(state.inset.left)) return;
        root.style.setProperty('--desktop-inset-top', state.inset.top + 'px');
        root.style.setProperty('--desktop-inset-left', state.inset.left + 'px');
        if (state.fullScreen === true) root.dataset.fullscreen = '';
        else delete root.dataset.fullscreen;
    }

    window.addEventListener('message', function (event) {
        if (event.source !== window || event.origin !== window.location.origin) return;
        var data = event.data;
        if (data && data.type === 'carnivore.window-chrome') apply(data);
    });

    var asked = bridge.windowChrome();
    if (asked && typeof asked.then === 'function') asked.then(apply, function () {  });
})();
