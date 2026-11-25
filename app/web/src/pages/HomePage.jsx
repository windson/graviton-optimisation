import { ProductGrid } from '../components/ProductCard.jsx';

export function HomePage({ data }) {
  return (
    <>
      <section className="hero">
        <h1>Everything for home, work and outdoors</h1>
        <p>Free delivery on orders over $50. Thirty day returns on every item.</p>
      </section>
      {data.featured.map((category) => (
        <section key={category.categoryId} className="shelf">
          <h2>
            <a href={`/c/${category.categoryId}`}>Top rated in {category.categoryName}</a>
          </h2>
          <ProductGrid products={category.topRated} />
        </section>
      ))}
      <section className="shelf">
        <h2>New arrivals</h2>
        <ProductGrid products={data.newArrivals} />
      </section>
    </>
  );
}
