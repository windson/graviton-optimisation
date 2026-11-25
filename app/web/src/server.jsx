import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import compress from '@fastify/compress';
import Fastify from 'fastify';
import { renderToString } from 'react-dom/server';
import { Pool } from 'undici';
import { App, titleFor } from './App.jsx';

const PORT = Number(process.env.PORT ?? 3000);
const API_BASE_URL = process.env.API_BASE_URL ?? 'http://127.0.0.1:8080';
const CATEGORY_TTL_MS = 60_000;
const SORTS = new Set(['rating', 'price', 'newest']);

// ---- API client -----------------------------------------------------------------------

const api = new Pool(API_BASE_URL, {
  connections: Number(process.env.API_CONNECTIONS ?? 32),
  keepAliveTimeout: 30_000,
  headersTimeout: 5_000,
  bodyTimeout: 5_000,
});

class UpstreamError extends Error {
  constructor(status, path) {
    super(`API returned ${status} for ${path}`);
    this.status = status;
  }
}

/** GETs JSON from the API. Returns null for 4xx (treated as "not found"), throws for 5xx. */
async function getJson(path) {
  const { statusCode, body } = await api.request({ method: 'GET', path, headers: { accept: 'application/json' } });
  if (statusCode >= 200 && statusCode < 300) {
    return body.json();
  }
  await body.dump();
  if (statusCode >= 400 && statusCode < 500) {
    return null;
  }
  throw new UpstreamError(statusCode, path);
}

// ---- Category cache -------------------------------------------------------------------
// Every page shows the full category menu. Categories change rarely, so the list is kept
// in memory and refreshed at most once a minute, with a single request in flight.

let categories = { nav: [], byId: new Map(), loadedAt: 0 };
let categoryRefresh = null;

/** Groups categories by department (the first word of the name) for the menu. */
function menu(all) {
  const groups = new Map();
  for (const { id, name } of all) {
    const department = name.split(' ')[0];
    if (!groups.has(department)) groups.set(department, []);
    groups.get(department).push({ id, name });
  }
  return [...groups].map(([department, list]) => ({ department, categories: list }));
}

async function loadCategories() {
  const all = (await getJson('/api/categories')) ?? [];
  categories = { nav: menu(all), byId: new Map(all.map((c) => [c.id, c])), loadedAt: Date.now() };
}

async function currentCategories() {
  if (Date.now() - categories.loadedAt > CATEGORY_TTL_MS) {
    categoryRefresh ??= loadCategories().finally(() => {
      categoryRefresh = null;
    });
    // Serve the previous list while a refresh is in flight, except on first load.
    if (categories.loadedAt === 0) {
      await categoryRefresh;
    } else {
      categoryRefresh.catch(() => {});
    }
  }
  return categories;
}

// ---- Rendering ------------------------------------------------------------------------

const escapeHtml = (text) =>
  String(text).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);

/** JSON that is safe inside a <script> element. */
const serialize = (value) => JSON.stringify(value).replace(/</g, '\\u003c');

function document(state) {
  const body = renderToString(<App state={state} />);
  return (
    '<!doctype html><html lang="en"><head><meta charset="utf-8">' +
    '<meta name="viewport" content="width=device-width, initial-scale=1">' +
    `<title>${escapeHtml(titleFor(state))}</title>` +
    '<link rel="stylesheet" href="/assets/app.css"></head><body>' +
    `<div id="root">${body}</div>` +
    `<script id="__STATE__" type="application/json">${serialize(state)}</script>` +
    '<script type="module" src="/assets/client.js"></script></body></html>'
  );
}

async function send(reply, page, data, extra = {}) {
  const { nav } = await currentCategories();
  const found = data !== null;
  const state = found ? { page, data, nav, ...extra } : { page: 'not-found', data: {}, nav };
  return reply
    .code(found ? 200 : 404)
    .header('content-type', 'text/html; charset=utf-8')
    .header('cache-control', 'private, no-store')
    .send(document(state));
}

const positiveInt = (value) => (/^[1-9][0-9]{0,8}$/.test(String(value)) ? Number(value) : null);

// ---- Server ---------------------------------------------------------------------------

export async function buildServer() {
  // keepAliveTimeout must exceed the load balancer's idle timeout (60 s).
  const app = Fastify({ logger: { level: process.env.LOG_LEVEL ?? 'warn' }, keepAliveTimeout: 75_000 });
  app.server.headersTimeout = 80_000;

  // Awaited so that the routes declared below are registered after the plugin and get compressed.
  await app.register(compress, { global: true, encodings: ['gzip'], threshold: 1024 });

  const assetDir = fileURLToPath(new URL('./public/', import.meta.url));
  const assets = {
    'client.js': ['text/javascript; charset=utf-8', readFileSync(`${assetDir}client.js`)],
    'app.css': ['text/css; charset=utf-8', readFileSync(`${assetDir}app.css`)],
  };
  app.get('/assets/:file', (request, reply) => {
    const asset = assets[request.params.file];
    if (!asset) return reply.code(404).send('not found');
    return reply.header('content-type', asset[0]).header('cache-control', 'public, max-age=3600').send(asset[1]);
  });

  app.get('/healthz', (request, reply) => reply.type('text/plain').send('ok'));

  app.get('/', async (request, reply) => send(reply, 'home', await getJson('/api/home')));

  app.get('/c/:id', async (request, reply) => {
    const id = positiveInt(request.params.id);
    if (id === null) return send(reply, 'category', null);
    const query = new URLSearchParams({ category: String(id) });
    if (SORTS.has(request.query.sort)) query.set('sort', request.query.sort);
    if (positiveInt(request.query.page) !== null) query.set('page', request.query.page);
    if (typeof request.query.brand === 'string' && request.query.brand) query.set('brand', request.query.brand);
    const data = await getJson(`/api/catalog?${query}`);
    const { byId } = await currentCategories();
    return send(reply, 'category', data, { category: byId.get(id) ?? null });
  });

  app.get('/p/:id', async (request, reply) => {
    const id = positiveInt(request.params.id);
    return send(reply, 'product', id === null ? null : await getJson(`/api/products/${id}`));
  });

  app.get('/search', async (request, reply) => {
    const q = typeof request.query.q === 'string' ? request.query.q.trim() : '';
    const data = q.length >= 2 ? await getJson(`/api/search?${new URLSearchParams({ q })}`) : null;
    return send(reply, 'search', data ?? { query: q, items: [] });
  });

  app.setNotFoundHandler((request, reply) => send(reply, 'not-found', null));

  app.setErrorHandler((error, request, reply) => {
    // The API is unreachable or failing: answer 502 so the caller can tell the tiers apart.
    request.log.error({ err: error }, 'request failed');
    const upstream = error instanceof UpstreamError || String(error.code ?? '').startsWith('UND_ERR');
    reply.code(upstream ? 502 : 500).type('text/plain').send(upstream ? 'upstream unavailable' : 'internal error');
  });

  return app;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const app = await buildServer();
  for (const signal of ['SIGTERM', 'SIGINT']) {
    process.once(signal, async () => {
      await app.close();
      await api.close();
      process.exit(0);
    });
  }
  await app.listen({ port: PORT, host: '0.0.0.0' });
}
