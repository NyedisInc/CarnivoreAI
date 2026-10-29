
'use strict';

const fs = require('fs');
const path = require('path');

const SCHEME = 'carnivore-page';
const TYPES = { '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'text/javascript; charset=utf-8' };

function registerLocalPageScheme(protocol) {
  protocol.registerSchemesAsPrivileged([{ scheme: SCHEME, privileges: { standard: true, secure: true } }]);
}

function serveLocalPage(ses, host, dir, page) {
  if (!ses.protocol.isProtocolHandled(SCHEME)) {
    ses.protocol.handle(SCHEME, async (request) => {
      const url = new URL(request.url);
      const name = decodeURIComponent(url.pathname.slice(1));
      const type = TYPES[path.extname(name)];
      if (url.host !== host || !type || name !== path.basename(name)) return new Response(null, { status: 404 });
      try {
        return new Response(await fs.promises.readFile(path.join(dir, name)), { headers: { 'content-type': type } });
      } catch (_missing) {
        return new Response(null, { status: 404 });
      }
    });
  }
  return `${SCHEME}://${host}/${page}`;
}

module.exports = { SCHEME, registerLocalPageScheme, serveLocalPage };
