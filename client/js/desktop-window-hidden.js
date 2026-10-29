/*  hidden  */
(function () {
    'use strict';

    if (typeof window === 'undefined' || !window.carnivoreDesktop) return;

    window.addEventListener('message', function (event) {
        if (event.source !== window || event.origin !== window.location.origin) return;
        var data = event.data;
        if (!data || data.type !== 'carnivore.window-hidden' || typeof data.hidden !== 'boolean') return;
        if (window.CarnivoreWindowHidden === data.hidden) return;
        window.CarnivoreWindowHidden = data.hidden;
        document.dispatchEvent(new Event('visibilitychange'));
    });
})();
