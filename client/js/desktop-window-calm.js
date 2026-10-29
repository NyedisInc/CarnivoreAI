(function () {
    'use strict';

    if (typeof window === 'undefined' || !window.carnivoreDesktop) return;

    var root = document.documentElement;

    function apply() {
        var reasons = [];
        if (window.CarnivoreWindowBlurred) reasons.push('blur');
        if (window.CarnivorePowerCalm && window.CarnivorePowerReason) reasons.push(window.CarnivorePowerReason);
        var was = root.getAttribute('data-calm') !== null;
        if (reasons.length) root.setAttribute('data-calm', reasons.join(' '));
        else root.removeAttribute('data-calm');
        if (was !== reasons.length > 0) {
            document.dispatchEvent(new CustomEvent('carnivore:calm', { detail: { calm: reasons.length > 0, reasons: reasons } }));
        }
    }

    window.addEventListener('message', function (event) {
        if (event.source !== window || event.origin !== window.location.origin) return;
        var data = event.data;
        if (!data) return;
        if (data.type === 'carnivore.window-blurred' && typeof data.blurred === 'boolean') {
            window.CarnivoreWindowBlurred = data.blurred;
        } else if (data.type === 'carnivore.power-calm' && typeof data.calm === 'boolean' &&
                   typeof data.reason === 'string' && /^[a-z-]{0,12}$/.test(data.reason)) {
            window.CarnivorePowerCalm = data.calm;
            window.CarnivorePowerReason = data.calm ? data.reason : '';
        } else {
            return;
        }
        apply();
    });
})();
