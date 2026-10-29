(function () {
    'use strict';

    function isHttpUrl(value) {
        var stripped = String(value == null ? '' : value).replace(/[\s\x00-\x1F]+/g, '').toLowerCase();
        return /^https?:\/\/[^/]/.test(stripped);
    }

    window.HttpUrl = { isHttpUrl: isHttpUrl };
    if (typeof module !== 'undefined' && module.exports) module.exports = window.HttpUrl;
})();
