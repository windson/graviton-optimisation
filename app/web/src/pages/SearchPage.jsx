import { ProductGrid } from '../components/ProductCard.jsx';

export function SearchPage({ data }) {
  return (
    <>
      <h1>Results for “{data.query}”</h1>
      {data.items.length === 0 ? <p>No products match your search.</p> : <ProductGrid products={data.items} />}
    </>
  );
}
