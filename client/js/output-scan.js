(function () {
    'use strict';

    var URL_RE = /\bhttps?:\/\/[^\s<>"'`]+/g;

    var CODE_RE = /(?:^|[\s:=>[(])([A-Z0-9][A-Z0-9_-]{5,63})(?=$|[\s.,;:)\]])/g;

    var TRAILING_JUNK = /[.,;:!?)\]}>'"]+$/;

    function trimTrailing(value) {
        return value.replace(TRAILING_JUNK, '');
    }

    function findUrls(text) {
        if (!text) return [];
        var out = [];
        var seen = Object.create(null);
        var m;
        URL_RE.lastIndex = 0;
        while ((m = URL_RE.exec(text)) !== null) {
            var url = trimTrailing(m[0]);
            if (url.length < 12) continue;
            if (seen[url]) continue;
            seen[url] = true;
            out.push(url);
        }
        return out.reverse();
    }

    function findCodes(text) {
        if (!text) return [];
        var urls = findUrls(text).join(' ');
        var out = [];
        var seen = Object.create(null);
        var padded = text + ' ';
        var m;
        CODE_RE.lastIndex = 0;
        while ((m = CODE_RE.exec(padded)) !== null) {
            var code = m[1];
            if (!/[0-9-]/.test(code)) continue;
            if (seen[code]) continue;
            if (urls.indexOf(code) !== -1) continue;
            seen[code] = true;
            out.push(code);
        }
        return out.reverse();
    }

    function scan(text, limit) {
        var max = typeof limit === 'number' ? limit : 12;
        var items = [];
        findUrls(text).forEach(function (u) {
            items.push({ kind: 'url', value: u });
        });
        findCodes(text).forEach(function (c) {
            items.push({ kind: 'code', value: c });
        });
        return items.slice(0, max);
    }

    window.OutputScan = {
        scan: scan,
        findUrls: findUrls,
        findCodes: findCodes
    };
})();
