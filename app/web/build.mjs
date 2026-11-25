// Builds the server bundle, the browser bundle and, with --test, the test bundle.
import { build } from 'esbuild';
import { cp, mkdir, rm } from 'node:fs/promises';

const production = { 'process.env.NODE_ENV': '"production"' };
const jsx = { jsx: 'automatic', loader: { '.jsx': 'jsx' } };
const testOnly = process.argv.includes('--test');

if (!testOnly) {
  await rm('dist', { recursive: true, force: true });
  await mkdir('dist/public', { recursive: true });

  // Server: application code only; node_modules stay external and are loaded at run time.
  await build({
    entryPoints: ['src/server.jsx'],
    outfile: 'dist/server.mjs',
    bundle: true,
    packages: 'external',
    platform: 'node',
    format: 'esm',
    target: 'node22',
    define: production,
    ...jsx,
  });

  // Browser: everything in one minified file, used to hydrate the server-rendered page.
  await build({
    entryPoints: ['src/client.jsx'],
    outfile: 'dist/public/client.js',
    bundle: true,
    minify: true,
    platform: 'browser',
    format: 'esm',
    target: 'es2022',
    define: production,
    ...jsx,
  });

  await cp('src/app.css', 'dist/public/app.css');
}

if (testOnly) {
  await build({
    entryPoints: ['test/render.test.jsx'],
    outfile: 'dist/test/render.test.mjs',
    bundle: true,
    packages: 'external',
    platform: 'node',
    format: 'esm',
    target: 'node22',
    define: production,
    ...jsx,
  });
}
