(function () {
    'use strict';

    function tr(key, params) {
        var i18n = globalThis.CloudeI18n;
        return i18n && typeof i18n.t === 'function' ? i18n.t(key, params) : key;
    }

    globalThis.CloudeTr = tr;
})();
