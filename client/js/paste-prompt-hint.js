(function () {
    'use strict';

    var PROMPT_THRESHOLD_MS = 500;

    function inNativeIosShell() {
        var shell = globalThis.carnivoreShell;
        return !!shell && shell.platform === 'ios';
    }

    function wasForcedToPrompt(elapsedMs, refused) {
        if (!inNativeIosShell()) return false;
        return refused === true || elapsedMs >= PROMPT_THRESHOLD_MS;
    }

    function isRefusal(err) {
        return !!err && err.name === 'NotAllowedError';
    }

    window.PastePromptHint = {
        PROMPT_THRESHOLD_MS: PROMPT_THRESHOLD_MS,
        inNativeIosShell: inNativeIosShell,
        wasForcedToPrompt: wasForcedToPrompt,
        isRefusal: isRefusal
    };
})();
