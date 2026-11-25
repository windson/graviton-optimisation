import { Layout } from './components/Layout.jsx';
import { CategoryPage } from './pages/CategoryPage.jsx';
import { HomePage } from './pages/HomePage.jsx';
import { ProductPage } from './pages/ProductPage.jsx';
import { SearchPage } from './pages/SearchPage.jsx';

const PAGES = {
  home: HomePage,
  category: CategoryPage,
  product: ProductPage,
  search: SearchPage,
};

/**
 * The same component tree renders on the server and hydrates in the browser.
 * `state` is everything a page needs: { page, data, nav, category }.
 */
export function App({ state }) {
  const Page = PAGES[state.page];
  return (
    <Layout nav={state.nav} query={state.page === 'search' ? state.data.query : undefined}>
      {Page ? <Page data={state.data} category={state.category} /> : <NotFound />}
    </Layout>
  );
}

function NotFound() {
  return (
    <section className="not-found">
      <h1>Page not found</h1>
      <p>
        The page you asked for does not exist. <a href="/">Go to the home page</a>.
      </p>
    </section>
  );
}

export function titleFor(state) {
  switch (state.page) {
    case 'category':
      return `${state.category?.name ?? 'Category'} | Storefront`;
    case 'product':
      return `${state.data.name} | Storefront`;
    case 'search':
      return `Search: ${state.data.query} | Storefront`;
    case 'home':
      return 'Storefront';
    default:
      return 'Not found | Storefront';
  }
}
