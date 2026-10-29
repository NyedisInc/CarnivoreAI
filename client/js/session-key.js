(function () {
    'use strict';

    function isLocal(hostKey) {
        return !hostKey || hostKey === 'local';
    }

    function forName(name, hostKey) {
        if (!name) return null;
        return isLocal(hostKey) ? name : 'remote:' + hostKey + ':' + name;
    }

    window.SessionKey = { isLocal: isLocal, forName: forName };
})();
