import assert from 'node:assert/strict';
import { test } from 'node:test';
import { renderToString } from 'react-dom/server';
import { App, titleFor } from '../src/App.jsx';

const kitchen = { id: 1, name: 'Kitchen Essentials', slug: 'category-1', productCount: 900 };
const nav = [{ department: 'Kitchen', categories: [{ id: 1, name: 'Kitchen Essentials' }] }];
const product = (id) => ({
  id,
  name: `Compact Oak Lamp ${id}`,
  brand: 'Atlas',
  price: 19.5,
  rating: 4.4,
  reviewCount: 12,
  image: `/img/p/${id}.jpg`,
});

test('category page renders the grid, facets and pagination', () => {
  const state = {
    page: 'category',
    nav,
    category: kitchen,
    data: {
      categoryId: 1,
      sort: 'price',
      brand: null,
      page: 2,
      hasNext: true,
      items: [product(1), product(2)],
      brands: [{ brand: 'Atlas', count: 7, minPrice: 5, maxPrice: 90 }],
      priceBands: [{ from: 0, to: 50, count: 9 }],
    },
  };
  const html = renderToString(<App state={state} />);

  assert.equal((html.match(/class="card"/g) ?? []).length, 2);
  assert.match(html, /\$19\.50/);
  assert.match(html, /href="\/c\/1\?sort=price&amp;brand=Atlas"/);
  assert.match(html, /href="\/c\/1\?sort=price&amp;page=3"/);
  assert.equal(titleFor(state), 'Kitchen Essentials | Storefront');
});

test('product page renders reviews and related products', () => {
  const state = {
    page: 'product',
    nav,
    data: {
      ...product(5),
      sku: 'SKU000000005',
      categoryId: 1,
      categoryName: 'Kitchen Essentials',
      description: 'Built for everyday use.',
      stock: 0,
      reviews: [{ id: 9, customerId: 3, rating: 5, title: 'Solid build quality', body: 'Works.', createdAt: '2026-10-01T10:00:00Z' }],
      alsoBought: [product(6)],
    },
  };
  const html = renderToString(<App state={state} />);

  assert.match(html, /Out of stock/);
  assert.match(html, /Solid build quality/);
  assert.match(html, /Oct 1, 2026/);
  assert.match(html, /Customers also bought/);
});

test('user input is escaped in the search page', () => {
  const state = { page: 'search', nav, data: { query: '<script>x</script>', items: [] } };
  const html = renderToString(<App state={state} />);

  assert.doesNotMatch(html, /<script>x/);
  assert.match(html, /No products match your search/);
});

test('unknown pages render the not-found view', () => {
  const html = renderToString(<App state={{ page: 'not-found', nav, data: {} }} />);

  assert.match(html, /Page not found/);
});
