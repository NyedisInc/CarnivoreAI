/**
 * A shared CSS-custom-property diff writer, for every theme paint path
 * that sets variables on an element's inline style - :root for the page
 * (registry.js's paintCssVars) and #terminal-screen for the terminal
 * scope (registry.js's paintTerminalScope).
 *
 * WHY A DIFF WRITER, NOT A WHOLE-CALL SKIP. Setting a CSS custom property
 * to the value it already holds still invalidates style for everything
 * that depends on it - a full ~30-variable palette reapplied unchanged
 * is real recalculation for zero visual difference. The fix has to be
 * PER PROPERTY. A whole-call skip keyed on "is this the same theme id"
 * would also skip a genuine value change hiding behind an unchanged id
 * (a manifest whose cssVars differ from what is actually applied right
 * now, for any reason), and it would skip exactly the thing this project
 * cannot afford to skip: REMOVING a variable the outgoing set does not
 * carry. `3d8d10e` made paintTerminalScope move the CSS scope and the
 * xterm palette TOGETHER, precisely so a variable is removed rather than
 * orphaned when the pin takes the scope off the agent; a skip that also
 * skipped that removal would reintroduce stale styling under a different
 * name. So removal here is UNCONDITIONAL - it is never gated on whether
 * anything else changed - and only the per-property SET is what gets to
 * check "is this already the value on the element" before writing.
 *
 * THIS FILE OWNS NO POLICY ABOUT WHEN TO REPAINT, only how to apply one
 * property set once the caller has decided to. It does not touch xterm
 * listeners, effects.js or persistence - those stay exactly where
 * they already lived, firing on every call as before. Folding this
 * writer's per-property skip into a caller that also skipped THOSE would
 * be a very different, much riskier change; this file structurally
 * cannot do that, because it never reaches into anything but one style
 * object and one plain values map.
 *
 * Exports window.ThemeVarWriter.
 */

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
