// Storefront workload for k6, run by Distributed Load Testing on AWS in native mode.
//
// tools/bench.py fills in the CONFIG constant below with the run's settings and uploads
// the result as a single script. Each load generator task runs its own copy, so the arrival rate in the
// config is the per-task share of the total rate.
//
// The load is open-loop: requests start on a fixed schedule whether or not earlier ones
// have finished. A slow system therefore sees its queue grow, as it would with real
// users, instead of the test slowing down to match it.
import http from 'k6/http';
import exec from 'k6/execution';

const CONFIG = {
  "baseUrl": "http://graviton-uplift-000000000.us-west-2.elb.amazonaws.com",
  "dataSet": {
    "categories": 500,
    "products": 1000000,
    "customers": 2000000
  },
  "mix": {
    "page_home": 6,
    "page_category": 10,
    "page_product": 12,
    "page_search": 3,
    "api_home": 2,
    "api_catalog": 4,
    "api_product": 14,
    "api_search": 1.5,
    "api_orders": 14,
    "api_cart_get": 20,
    "api_cart_put": 9,
    "api_order_post": 4.5
  },
  "oneWordSearchShare": 0.25,
  "timeout": "5s",
  "timeUnit": "1m",
  "preAllocatedVUs": 71,
  "maxVUs": 600,
  "startRate": 3408,
  "stages": [
    {
      "target": 17040,
      "duration": "60s"
    },
    {
      "target": 17040,
      "duration": "600s"
    }
  ],
  "windows": [
    {
      "fromMs": 0,
      "toMs": 70000,
      "label": "ramp"
    },
    {
      "fromMs": 70000,
      "toMs": 660000,
      "label": null
    }
  ]
};

export const options = {
  // Response bodies are not needed to time a request.
  discardResponseBodies: true,
  // Only the tags the DLT result reducer reads. Fewer tags keep the raw output small.
  systemTags: ['name', 'status', 'error_code', 'method', 'scenario'],
  scenarios: {
    load: {
      executor: 'ramping-arrival-rate',
      startRate: CONFIG.startRate,
      timeUnit: CONFIG.timeUnit,
      stages: CONFIG.stages,
      preAllocatedVUs: CONFIG.preAllocatedVUs,
      maxVUs: CONFIG.maxVUs,
      gracefulStop: '10s',
    },
  },
};

const BASE = CONFIG.baseUrl;
const DATA = CONFIG.dataSet; // { categories, products, customers }
const HTML = { headers: { Accept: 'text/html', 'Accept-Encoding': 'gzip' }, timeout: CONFIG.timeout };
const JSON_GET = { headers: { Accept: 'application/json', 'Accept-Encoding': 'gzip' }, timeout: CONFIG.timeout };
const JSON_SEND = {
  headers: { Accept: 'application/json', 'Accept-Encoding': 'gzip', 'Content-Type': 'application/json' },
  timeout: CONFIG.timeout,
};

// Same vocabulary as the data generator (app/api/.../seed/Words.java).
const ADJECTIVES = [
  'Compact', 'Durable', 'Elegant', 'Foldable', 'Heavy', 'Light', 'Modern', 'Portable', 'Quiet', 'Rugged',
  'Sleek', 'Smart', 'Sturdy', 'Vintage', 'Wireless', 'Adjustable', 'Breathable', 'Classic', 'Deluxe', 'Eco',
  'Flexible', 'Glossy', 'Handmade', 'Insulated', 'Jumbo', 'Kinetic', 'Luxe', 'Minimal', 'Nordic', 'Organic',
  'Premium', 'Rapid', 'Slim', 'Tactical', 'Ultra', 'Versatile', 'Waterproof', 'Zen', 'Bold', 'Crisp',
];
const MATERIALS = [
  'Aluminum', 'Bamboo', 'Canvas', 'Ceramic', 'Copper', 'Cork', 'Cotton', 'Glass', 'Granite', 'Leather',
  'Linen', 'Marble', 'Mesh', 'Nylon', 'Oak', 'Steel', 'Titanium', 'Walnut', 'Wool', 'Carbon',
  'Silicone', 'Rubber', 'Brass', 'Maple', 'Denim', 'Fleece', 'Suede', 'Acrylic', 'Birch', 'Hemp',
];

// ---- Random choices. Each follows the same skew the data generator used, so popular
// ---- categories, products and customers get most of the traffic. ----------------------

const pick = (list) => list[Math.floor(Math.random() * list.length)];
const skewed = (n, exponent) => 1 + Math.floor(n * Math.pow(Math.random(), exponent));
const category = () => skewed(DATA.categories, 1.5);
const product = () => skewed(DATA.products, 3);
const frequentCustomer = () => skewed(DATA.customers, 2);
const anyCustomer = () => 1 + Math.floor(Math.random() * DATA.customers);

function listingQuery() {
  const r = Math.random();
  const sort = r < 0.6 ? 'rating' : r < 0.85 ? 'price' : 'newest';
  const p = Math.random();
  const page = p < 0.7 ? 1 : p < 0.9 ? 2 : 3;
  return `sort=${sort}&page=${page}`;
}

// A quarter of searches are a single word, which matches about 2.5% of the catalog.
const searchTerm = () =>
  encodeURIComponent(Math.random() < CONFIG.oneWordSearchShare ? pick(ADJECTIVES) : `${pick(ADJECTIVES)} ${pick(MATERIALS)}`);

// The product in each of a customer's three cart slots is a fixed function of the
// customer, matching the seeded rows, so cart writes update rows and the table stays
// the same size from run to run.
const cartProduct = (customer, slot) => 1 + ((customer * 2654435761 + slot * 40503) % DATA.products);

// ---- Operations -----------------------------------------------------------------------
// Pages are rendered by the web tier, which calls the API once per page. API operations
// are the calls a browser or mobile app makes directly.

const OPERATIONS = {
  page_home: (tags) => http.get(`${BASE}/`, { ...HTML, tags }),
  page_category: (tags) => http.get(`${BASE}/c/${category()}?${listingQuery()}`, { ...HTML, tags }),
  page_product: (tags) => http.get(`${BASE}/p/${product()}`, { ...HTML, tags }),
  page_search: (tags) => http.get(`${BASE}/search?q=${searchTerm()}`, { ...HTML, tags }),
  api_home: (tags) => http.get(`${BASE}/api/home`, { ...JSON_GET, tags }),
  api_catalog: (tags) => http.get(`${BASE}/api/catalog?category=${category()}&${listingQuery()}`, { ...JSON_GET, tags }),
  api_product: (tags) => http.get(`${BASE}/api/products/${product()}`, { ...JSON_GET, tags }),
  api_search: (tags) => http.get(`${BASE}/api/search?q=${searchTerm()}`, { ...JSON_GET, tags }),
  api_orders: (tags) => http.get(`${BASE}/api/customers/${frequentCustomer()}/orders`, { ...JSON_GET, tags }),
  api_cart_get: (tags) => http.get(`${BASE}/api/cart/${anyCustomer()}`, { ...JSON_GET, tags }),
  api_cart_put: (tags) => {
    const customer = anyCustomer();
    const slot = Math.floor(Math.random() * 3);
    const body = JSON.stringify({ qty: 1 + Math.floor(Math.random() * 5) });
    return http.put(`${BASE}/api/cart/${customer}/items/${cartProduct(customer, slot)}`, body, { ...JSON_SEND, tags });
  },
  api_order_post: (tags) => {
    const lines = 1 + Math.floor(Math.random() * 3);
    const items = [];
    for (let i = 0; i < lines; i++) {
      items.push({ productId: product(), qty: 1 + Math.floor(Math.random() * 2) });
    }
    return http.post(`${BASE}/api/orders`, JSON.stringify({ customerId: anyCustomer(), items }), { ...JSON_SEND, tags });
  },
};

// Cumulative weights for choosing an operation.
const MIX = [];
let totalWeight = 0;
for (const [name, weight] of Object.entries(CONFIG.mix)) {
  if (!OPERATIONS[name]) throw new Error(`unknown operation in mix: ${name}`);
  if (weight > 0) {
    totalWeight += weight;
    MIX.push([totalWeight, name]);
  }
}

function chooseOperation() {
  const r = Math.random() * totalWeight;
  for (const [limit, name] of MIX) {
    if (r < limit) return name;
  }
  return MIX[MIX.length - 1][1];
}

// ---- Labelling ------------------------------------------------------------------------
// DLT keeps one latency histogram per request name. A run is divided into windows:
// a window either labels requests by operation (steady measurement), or gives every
// request the window's own label (ramps, and each step of a capacity run).

function windowLabel(elapsedMs) {
  for (const w of CONFIG.windows) {
    if (elapsedMs >= w.fromMs && elapsedMs < w.toMs) return w.label;
  }
  return 'outside';
}

export default function () {
  const operation = chooseOperation();
  const label = windowLabel(exec.instance.currentTestRunDuration);
  OPERATIONS[operation]({ name: label === null ? operation : label });
}
