import { ProductGrid, Stars } from '../components/ProductCard.jsx';
import { date, money } from '../format.js';

export function ProductPage({ data }) {
  return (
    <>
      <nav className="breadcrumb" aria-label="Breadcrumb">
        <a href="/">Home</a> / <a href={`/c/${data.categoryId}`}>{data.categoryName}</a> / <span>{data.name}</span>
      </nav>
      <article className="product">
        <img className="product-image" src={data.image} alt={data.name} width="480" height="480" />
        <div className="product-info">
          <p className="brand">{data.brand}</p>
          <h1>{data.name}</h1>
          <p className="rating">
            <Stars rating={data.rating} /> {data.rating} <span className="count">({data.reviewCount} reviews)</span>
          </p>
          <p className="price">{money(data.price)}</p>
          <p className={data.stock > 0 ? 'stock in' : 'stock out'}>{data.stock > 0 ? 'In stock' : 'Out of stock'}</p>
          <button type="button" className="add" data-product={data.id}>Add to cart</button>
          <p className="sku">SKU {data.sku}</p>
          <p className="description">{data.description}</p>
        </div>
      </article>
      <section className="reviews">
        <h2>Latest reviews</h2>
        {data.reviews.length === 0 && <p>No reviews yet.</p>}
        {data.reviews.map((review) => (
          <article key={review.id} className="review">
            <h3>{review.title}</h3>
            <p className="rating">
              <Stars rating={review.rating} /> <time dateTime={review.createdAt}>{date(review.createdAt)}</time>
            </p>
            <p>{review.body}</p>
          </article>
        ))}
      </section>
      {data.alsoBought.length > 0 && (
        <section className="shelf">
          <h2>Customers also bought</h2>
          <ProductGrid products={data.alsoBought} />
        </section>
      )}
    </>
  );
}
