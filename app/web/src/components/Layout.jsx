const FOOTER_LINKS = [
  ['Shop', ['New arrivals', 'Best sellers', 'Gift cards', 'Clearance', 'Brands']],
  ['Help', ['Shipping', 'Returns', 'Order status', 'Size guides', 'Contact us']],
  ['Company', ['About', 'Careers', 'Press', 'Sustainability', 'Affiliates']],
  ['Legal', ['Terms', 'Privacy', 'Cookies', 'Accessibility', 'Licenses']],
];

/** `nav` is the full category tree: [{ department, categories: [{ id, name }] }]. */
export function Layout({ nav, query, children }) {
  return (
    <div className="page">
      <header className="site-header">
        <a className="logo" href="/">Storefront</a>
        <form className="search" action="/search" method="get" role="search">
          <input type="search" name="q" defaultValue={query ?? ''} placeholder="Search products" aria-label="Search products" />
          <button type="submit">Search</button>
        </form>
        <a className="cart-link" href="/cart">Cart</a>
      </header>
      <nav className="mega-menu" aria-label="Categories">
        <ul>
          {nav.map((group) => (
            <li key={group.department} className="department">
              <span className="department-name">{group.department}</span>
              <ul>
                {group.categories.map((category) => (
                  <li key={category.id}>
                    <a href={`/c/${category.id}`}>{category.name}</a>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      </nav>
      <main>{children}</main>
      <footer className="site-footer">
        {FOOTER_LINKS.map(([heading, links]) => (
          <section key={heading}>
            <h2>{heading}</h2>
            <ul>
              {links.map((link) => (
                <li key={link}>
                  <a href="#">{link}</a>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </footer>
    </div>
  );
}
