import { readdirSync, existsSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';

const CONFIG_NAME = 'vite.bundle.config.ts';

export function findConfigs(webDir) {
  const root = join(webDir, 'src', 'plugins');
  if (!existsSync(root)) return [];
  return readdirSync(root, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && existsSync(join(root, entry.name, CONFIG_NAME)))
    .map((entry) => `src/plugins/${entry.name}/${CONFIG_NAME}`)
    .sort();
}

export function main(argv) {
  const webIndex = argv.indexOf('--web');
  const webDir = webIndex >= 0 ? argv[webIndex + 1] : fileURLToPath(new URL('..', import.meta.url));
  const configs = findConfigs(webDir);
  if (argv.includes('--list')) {
    for (const config of configs) console.log(config);
    return 0;
  }
  for (const config of configs) {
    const done = spawnSync('npx', ['vite', 'build', '--config', config], { cwd: webDir, stdio: 'inherit' });
    if (done.status !== 0) return done.status ?? 1;
  }
  return 0;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) process.exit(main(process.argv.slice(2)));
