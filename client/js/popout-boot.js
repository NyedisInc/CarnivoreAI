(function () {
    'use strict';

    if (window.AppEvents && typeof window.AppEvents.start === 'function') {
        try {
            window.AppEvents.start();
        } catch (err) {
            console.warn('popout: event channel failed to start', err);
        }
    }

    var themes = window.Themes;
    if (!themes || typeof themes.init !== 'function') return;
    var prefs = window.Preferences;
    var hydrated = prefs && typeof prefs.hydrate === 'function'
        ? Promise.resolve(prefs.hydrate()).catch(function (err) {
            console.warn('popout: preferences hydrate failed, using the local theme copy', err);
        })
        : Promise.resolve();
    hydrated.then(function () { return themes.init(); }).catch(function (err) {
        console.warn('popout: theme init failed, using stylesheet defaults', err);
    });
})();
