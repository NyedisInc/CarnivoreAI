
console.log('[EffortLevel Module] Loading...');

(function () {
    'use strict';

    var LEVELS = ['low', 'medium', 'high', 'xhigh', 'max', 'ultracode'];

    function level(effort) {
        if (typeof effort !== 'string') return null;
        var norm = effort.trim().toLowerCase();
        return LEVELS.indexOf(norm) === -1 ? null : norm;
    }

    function className(effort) {
        var norm = level(effort);
        return norm ? 'effort-level effort--' + norm : '';
    }

    window.EffortLevel = { LEVELS: LEVELS, level: level, className: className };
})();
