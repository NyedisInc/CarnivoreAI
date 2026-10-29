
console.log('[NavigationGeneration Module] Loading...');

(function () {
    'use strict';

    var generation = 0;

    var currentTarget = null;

    function begin(target) {
        generation += 1;
        currentTarget = describeTarget(target);
        return generation;
    }

    function current() {
        return generation;
    }

    function isCurrent(token) {
        return typeof token === 'number' && token === generation;
    }

    function keep(token, what) {
        if (isCurrent(token)) return true;
        console.debug(
            '[nav] dropped ' + (what || 'work') + ' from a superseded navigation',
            { token: token, current: generation, target: currentTarget }
        );
        return false;
    }

    function describeTarget(target) {
        if (target == null) return null;
        if (typeof target === 'string') return target;
        if (typeof target === 'object') {
            var inner = (target.session && typeof target.session === 'object')
                ? target.session
                : target;
            return String(target.tmux_session || inner.tmux_session
                || inner.id || inner.name || '[object]');
        }
        return String(target);
    }

    window.NavigationGeneration = {
        begin: begin,
        current: current,
        isCurrent: isCurrent,
        keep: keep
    };
})();

console.log('[NavigationGeneration Module] Exported as window.NavigationGeneration');
