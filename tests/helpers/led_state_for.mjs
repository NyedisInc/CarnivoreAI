
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));

function loadStatusLed() {
    const src = fs.readFileSync(
        path.join(here, '..', '..', 'client', 'js', 'status-led.js'),
        'utf8'
    );
    const sandbox = { console: { log() {}, warn() {}, error() {} } };
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(src, sandbox, { filename: 'status-led.js' });
    if (!sandbox.StatusLed || typeof sandbox.StatusLed.ledStateFor !== 'function') {
        throw new Error('status-led.js did not publish StatusLed.ledStateFor');
    }
    return sandbox.StatusLed;
}

async function readStdin() {
    const chunks = [];
    for await (const chunk of process.stdin) chunks.push(chunk);
    return Buffer.concat(chunks).toString('utf8');
}

const raw = await readStdin();
let row;
try {
    row = JSON.parse(raw);
} catch (err) {
    process.stderr.write(`could not parse the row as JSON: ${err.message}\n`);
    process.exit(2);
}
const led = loadStatusLed().ledStateFor(row);
process.stdout.write(JSON.stringify({ inner: led.inner, outer: led.outer }));
