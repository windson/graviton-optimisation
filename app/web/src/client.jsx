import { hydrateRoot } from 'react-dom/client';
import { App } from './App.jsx';

const state = JSON.parse(document.getElementById('__STATE__').textContent);
hydrateRoot(document.getElementById('root'), <App state={state} />);

// "Add to cart" is the one interaction that needs JavaScript. A demo customer id
// stands in for a signed-in user.
const DEMO_CUSTOMER = 1;
document.addEventListener('click', async (event) => {
  const button = event.target.closest('button.add');
  if (!button) return;
  button.disabled = true;
  try {
    const response = await fetch(`/api/cart/${DEMO_CUSTOMER}/items/${button.dataset.product}`, {
      method: 'PUT',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ qty: 1 }),
    });
    button.textContent = response.ok ? 'Added' : 'Try again';
  } catch {
    button.textContent = 'Try again';
  } finally {
    button.disabled = false;
  }
});
