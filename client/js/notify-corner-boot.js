(function () {
    'use strict';
    var themes = window.Themes;
    if (!themes || typeof themes.init !== 'function') return;
    var prefs = window.Preferences;
    var hydrated = prefs && typeof prefs.hydrate === 'function'
        ? Promise.resolve(prefs.hydrate()).catch(function (err) {
            console.warn('notify-corner: preferences hydrate failed, using the local theme copy', err);
        })
        : Promise.resolve();
    hydrated.then(function () { return themes.init(); }).catch(function (err) {
        console.warn('notify-corner: theme init failed, using stylesheet defaults', err);
    });
})();
