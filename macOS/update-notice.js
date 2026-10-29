'use strict';

function createUpdateNotice({ Notification, memo, t, onInstall, bannersPosting }) {
  let shown = null;
  return {
    async onUx(ux) {
      if (!ux || !ux.notify || !ux.menuRow) return false;
      // permission prompt
      let posting = false;
      try {
        posting = (await bannersPosting()) === true;
      } catch (err) {
        console.warn('[update-notice] banners answer failed, no notice:', err.message);
      }
      if (!posting || !Notification.isSupported()) return false;
      const { version } = ux.menuRow;
      if (!memo.shouldAnnounce(version)) return false;
      const note = new Notification({
        title: t('menubar.update.notice.title', { version }),
        body: t('menubar.update.notice.body'),
        actions: [{ type: 'button', text: t('menubar.update.notice.button') }],
      });
      note.on('action', onInstall);
      note.on('click', onInstall);
      shown = note;
      note.show();
      return Boolean(shown);
    },
  };
}

module.exports = { createUpdateNotice };
