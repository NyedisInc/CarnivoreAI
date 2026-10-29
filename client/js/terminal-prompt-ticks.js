(function (global) {
    'use strict';

    var TICK_MIN_GAP = 4;

    function layoutTicks(prompts, bufferLength, railHeight) {
        var out = [];
        if (!prompts || prompts.length === 0) return out;
        var height = railHeight > 0 ? railHeight : 0;
        var denom = bufferLength > 0 ? bufferLength : 1;
        var maxTicks = height > 0
            ? Math.max(1, Math.floor(height / TICK_MIN_GAP))
            : prompts.length;
        var perTick = Math.max(1, Math.ceil(prompts.length / maxTicks));

        for (var i = 0; i < prompts.length; i += perTick) {
            var group = prompts.slice(i, i + perTick);
            var sum = 0;
            var ordinals = [];
            for (var k = 0; k < group.length; k++) {
                sum += (group[k].line / denom) * height;
                ordinals.push(group[k].ordinal);
            }
            out.push({ ordinals: ordinals, y: sum / group.length });
        }

        var prev = -Infinity;
        for (var j = 0; j < out.length; j++) {
            if (out[j].y < prev + TICK_MIN_GAP) out[j].y = prev + TICK_MIN_GAP;
            if (height > 0 && out[j].y > height) out[j].y = height;
            out[j].y = Math.round(out[j].y);
            prev = out[j].y;
        }
        return out;
    }

    function currentOrdinalFor(prompts, viewportY) {
        if (!prompts || prompts.length === 0) return 0;
        var found = 0;
        for (var i = 0; i < prompts.length; i++) {
            if (prompts[i].line <= viewportY) found = prompts[i].ordinal;
            else break;
        }
        return found || prompts[0].ordinal;
    }

    global.TerminalPromptTicks = {
        layoutTicks: layoutTicks,
        currentOrdinalFor: currentOrdinalFor,
        TICK_MIN_GAP: TICK_MIN_GAP
    };
}(typeof window !== 'undefined' ? window : globalThis));
