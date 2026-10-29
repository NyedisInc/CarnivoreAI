(function () {
    'use strict';

    var CONSUMER_SCREEN_IDS = ['launchpad-screen', 'terminal-screen'];

    function bundle() {
        var found = globalThis.CloudeWeb;
        return found
            && typeof found.resumeHomePolls === 'function'
            && typeof found.pauseHomePolls === 'function'
            ? found
            : null;
    }

    function wanted() {
        for (var i = 0; i < CONSUMER_SCREEN_IDS.length; i += 1) {
            var screen = document.getElementById(CONSUMER_SCREEN_IDS[i]);
            if (screen && screen.classList.contains('active')) return true;
        }
        return false;
    }

    function sync() {
        var app = bundle();
        if (!app) return;
        try {
            if (wanted()) app.resumeHomePolls();
            else app.pauseHomePolls();
        } catch (err) {
            console.warn('[DashboardPolls] the bundle refused a poll change', err);
        }
    }

    globalThis.DashboardPolls = {
        sync: sync,
        wanted: wanted,
        CONSUMER_SCREEN_IDS: CONSUMER_SCREEN_IDS,
    };
})();
