(function () {
    'use strict';

    function isPageOwner(role) {
        return !!(role && role.pageOwner === true);
    }

    window.TerminalPageOwner = {
        isPageOwner: isPageOwner
    };
})();
