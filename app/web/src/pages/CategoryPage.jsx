import { ProductGrid } from '../components/ProductCard.jsx';
import { money } from '../format.js';

const SORTS = [
  ['rating', 'Top rated'],
  ['price', 'Price: low to high'],
  ['newest', 'Newest'],
];

function href(categoryId, { sort, brand, page }) {
  const params = new URLSearchParams();
  if (sort && sort !== 'rating') params.set('sort', sort);
  if (brand) params.set('brand', brand);
  if (page && page > 1) params.set('page', String(page));
  const query = params.toString();
  return `/c/${categoryId}${query ? `?${query}` : ''}`;
}

export function CategoryPage({ data, category }) {
  const { categoryId, sort, brand, page } = data;
  return (
    <>
      <nav className="breadcrumb" aria-label="Breadcrumb">
        <a href="/">Home</a> / <span>{category?.name ?? `Category ${categoryId}`}</span>
      </nav>
      <h1>{category?.name ?? `Category ${categoryId}`}</h1>
      <div className="listing">
        <aside className="facets">
          <h2>Brand</h2>
          <ul>
            {data.brands.map((facet) => (
              <li key={facet.brand}>
                <a href={href(categoryId, { sort, brand: facet.brand })} className={facet.brand === brand ? 'active' : undefined}>
                  {facet.brand}
                </a>{' '}
                <span className="count">({facet.count})</span>
                <span className="range">
                  {money(facet.minPrice)} to {money(facet.maxPrice)}
                </span>
              </li>
            ))}
          </ul>
          <h2>Price</h2>
          <ul>
            {data.priceBands.map((band) => (
              <li key={band.from}>
                {money(band.from)} to {money(band.to)} <span className="count">({band.count})</span>
              </li>
            ))}
          </ul>
        </aside>
        <section className="results">
          <p className="sort">
            Sort by:{' '}
            {SORTS.map(([value, label]) => (
              <a key={value} href={href(categoryId, { sort: value, brand })} className={value === sort ? 'active' : undefined}>
                {label}
              </a>
            ))}
          </p>
          <ProductGrid products={data.items} />
          <p className="pagination">
            {page > 1 && <a href={href(categoryId, { sort, brand, page: page - 1 })}>Previous</a>}
            <span>Page {page}</span>
            {data.hasNext && <a href={href(categoryId, { sort, brand, page: page + 1 })}>Next</a>}
          </p>
        </section>
      </div>
    </>
  );
}
