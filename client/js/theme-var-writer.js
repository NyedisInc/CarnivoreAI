
console.log('[ThemeVarWriter Module] Loading...');

(function () {
    'use strict';

    function applyVarDiff(style, previous, next) {
        var prev = previous || {};
        var nextVars = next || {};
        var nextNames = Object.keys(nextVars);
        var i;
        var nextSet = Object.create(null);
        for (i = 0; i < nextNames.length; i++) nextSet[nextNames[i]] = true;

        var prevNames = Object.keys(prev);
        for (i = 0; i < prevNames.length; i++) {
            var stale = prevNames[i];
            if (!nextSet[stale]) {
                try { style.removeProperty(stale); } catch (_) {  }
            }
        }

        var values = {};
        var skipped = 0;
        for (i = 0; i < nextNames.length; i++) {
            var name = nextNames[i];
            var value = String(nextVars[name]);
            if (Object.prototype.hasOwnProperty.call(prev, name) && prev[name] === value) {
                values[name] = value;
                skipped++;
                continue;
            }
            try { style.setProperty(name, value); } catch (_) {  }
            values[name] = value;
        }

        return { values: values, skipped: skipped, total: nextNames.length };
    }

    window.ThemeVarWriter = { applyVarDiff: applyVarDiff };
    console.log('[ThemeVarWriter Module] Exported as window.ThemeVarWriter');
})();
