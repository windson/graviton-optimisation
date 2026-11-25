import { money } from '../format.js';

const SWATCHES = ['Charcoal', 'Sand', 'Forest', 'Ocean'];
/** List price shown struck through next to the selling price. */
const LIST_PRICE_FACTOR = 1.2;

export function Stars({ rating }) {
  const filled = Math.round(Number(rating));
  return (
    <span className="stars" role="img" aria-label={`${rating} out of 5`}>
      {[1, 2, 3, 4, 5].map((n) => (
        <span key={n} className={n <= filled ? 'star on' : 'star'}>★</span>
      ))}
    </span>
  );
}

function badges(product) {
  const list = [];
  if (product.reviewCount >= 1000) list.push('Best seller');
  if (Number(product.rating) >= 4.7) list.push('Top rated');
  if (Number(product.price) < 20) list.push('Under $20');
  return list;
}

export function ProductCard({ product }) {
  const listPrice = Number(product.price) * LIST_PRICE_FACTOR;
  return (
    <article className="card">
      <a href={`/p/${product.id}`} className="card-image">
        <img src={product.image} alt="" width="240" height="240" loading="lazy" />
      </a>
      <ul className="badges">
        {badges(product).map((badge) => (
          <li key={badge}>{badge}</li>
        ))}
      </ul>
      <div className="card-body">
        <p className="brand">{product.brand}</p>
        <h3>
          <a href={`/p/${product.id}`}>{product.name}</a>
        </h3>
        <p className="rating">
          <Stars rating={product.rating} />
          <span className="score">{product.rating}</span>
          <span className="count">({product.reviewCount})</span>
        </p>
        <p className="price">
          <span className="now">{money(product.price)}</span>
          <s className="was">{money(listPrice)}</s>
          <span className="saving">Save {money(listPrice - Number(product.price))}</span>
        </p>
        <ul className="swatches" aria-label="Colors">
          {SWATCHES.map((color) => (
            <li key={color} className={`swatch ${color.toLowerCase()}`} title={color} />
          ))}
        </ul>
        <p className="delivery">Free delivery on orders over $50</p>
        <div className="actions">
          <button type="button" className="add" data-product={product.id}>Add to cart</button>
          <button type="button" className="wish" aria-label={`Save ${product.name} for later`}>♡</button>
        </div>
      </div>
    </article>
  );
}

export function ProductGrid({ products }) {
  return (
    <div className="grid">
      {products.map((product) => (
        <ProductCard key={product.id} product={product} />
      ))}
    </div>
  );
}
