/*  hidden  overflow: hidden */

console.log('[LaunchpadHost Module] Loading...');

(function () {
    var SCREEN_ID = 'launchpad-screen';

    var BODY_CLASS = 'home-opscenter';

    var applied = false;

    function apply(onHome) {
        if (onHome === applied) return;
        applied = onHome;
        var body = document.body;
        if (!body) return;
        if (onHome) body.classList.add(BODY_CLASS);
        else body.classList.remove(BODY_CLASS);
        if (globalThis.DashboardPolls) globalThis.DashboardPolls.sync();
    }

    function homeIsActive() {
        var screen = document.getElementById(SCREEN_ID);
        return !!screen && screen.classList.contains('active');
    }

    function enter() {
        apply(true);
    }

    /* something else */
    function exit() {
        apply(false);
    }

    function observe() {
        var screen = document.getElementById(SCREEN_ID);
        if (!screen || typeof MutationObserver !== 'function') return;
        new MutationObserver(function () {
            apply(homeIsActive());
        }).observe(screen, { attributes: true, attributeFilter: ['class'] });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', observe, { once: true });
    } else {
        observe();
    }

    globalThis.LaunchpadHost = {
        enter: enter,
        exit: exit,
        apply: apply,
        homeIsActive: homeIsActive,
        BODY_CLASS: BODY_CLASS,
    };

    console.log('[LaunchpadHost Module] Loaded');
})();
