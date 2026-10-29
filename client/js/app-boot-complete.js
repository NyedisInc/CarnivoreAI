/* event that starts */

console.log('[AppBootComplete Module] Loading...');

(function () {
    /* and the real */
    var EVENT = 'app-boot-complete';

    /** @type {boolean} Whether the announcement has already gone out. */
    var announced = false;

    function announce() {
        if (announced) return;
        announced = true;
        try {
            window.dispatchEvent(new CustomEvent(EVENT));
        } catch (err) {
            console.warn('AppBootComplete: could not dispatch', err);
        }
    }

    function isComplete() {
        return announced;
    }

    window.AppBootComplete = {
        EVENT: EVENT,
        announce: announce,
        isComplete: isComplete
    };
})();
