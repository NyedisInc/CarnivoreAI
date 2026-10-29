/*  hidden  */

console.log('[ScreenChrome Module] Loading...');

const AUTHENTICATED_SCREENS = ['launchpad', 'terminal'];

const ScreenChrome = {
    apply(screen) {
        const body = document.body;
        if (!body) return;
        const name = typeof screen === 'string' ? screen : '';
        body.dataset.screen = name;
        body.classList.toggle(
            'is-authenticated',
            AUTHENTICATED_SCREENS.indexOf(name) !== -1
        );
    },

    isAuthenticated(screen) {
        return AUTHENTICATED_SCREENS.indexOf(screen) !== -1;
    },

    /** @type {string[]} the authenticated screen names, for tests. */
    AUTHENTICATED_SCREENS
};

window.ScreenChrome = ScreenChrome;
console.log('[ScreenChrome Module] Loaded');
