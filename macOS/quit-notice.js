'use strict';

const nodeFs = require('fs');
const path = require('path');

const FLAG = 'quit-notice-shown.flag';

function createQuitNotice({ dir, dialog, loadTranslator, fsImpl }) {
  const fs = fsImpl || nodeFs;
  const flag = () => path.join(dir(), FLAG);
  return {
    alreadyShown: () => fs.existsSync(flag()),
    async show() {
      try {
        fs.mkdirSync(dir(), { recursive: true });
        fs.writeFileSync(flag(), `${new Date().toISOString()}\n`, { mode: 0o600 });
      } catch (err) {
        console.warn('[quit-notice] flag not written, notice skipped:', err.message);
        return;
      }
      let t = (key) => key;
      try {
        t = await loadTranslator();
      } catch (err) {
        console.error('[quit-notice] string catalog did not load:', err && err.message);
      }
      await dialog.showMessageBox({
        type: 'info',
        title: t('desktop.quit_notice.title'),
        message: t('desktop.quit_notice.title'),
        detail: t('desktop.quit_notice.body'),
        buttons: [t('desktop.quit_notice.ok')],
        defaultId: 0,
      });
    },
  };
}

module.exports = { FLAG, createQuitNotice };
