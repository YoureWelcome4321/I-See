const grid = document.querySelector('#catalog-grid');
const status = document.querySelector('#catalog-status');
const count = document.querySelector('#catalog-count');

function renderProducts(products) {
  grid.replaceChildren();
  products.forEach((product) => {
    const card = document.createElement('article');
    card.className = 'catalog-product-card';
    const art = document.createElement('div'); art.className = 'catalog-product-art';
    const category = document.createElement('span'); category.className = 'catalog-product-category'; category.textContent = product.category || 'Продукт';
    const mark = document.createElement('span'); mark.className = 'catalog-product-mark'; mark.textContent = product.name.slice(0, 1);
    const sparkle = document.createElement('span'); sparkle.className = 'catalog-product-sparkle'; sparkle.setAttribute('aria-hidden', 'true'); sparkle.textContent = '✦';
    art.append(category, mark, sparkle);
    const body = document.createElement('div'); body.className = 'catalog-product-body';
    const heading = document.createElement('div'); heading.className = 'catalog-product-heading';
    const title = document.createElement('h3'); title.textContent = product.name;
    const price = document.createElement('span'); price.className = 'catalog-product-price'; price.textContent = product.price ? `${new Intl.NumberFormat('ru-RU').format(product.price)} ₽` : '—';
    heading.append(title, price);
    const description = document.createElement('p');
    const composition = product.ingredients ? `Состав: ${product.ingredients}` : 'Сведения о составе пока не добавлены.';
    description.textContent = composition.length > 116 ? `${composition.slice(0, 113).trimEnd()}…` : composition;
    const allergenNote = document.createElement('p'); allergenNote.className = 'catalog-product-allergens';
    allergenNote.textContent = product.allergens ? `В составе указано: ${product.allergens}` : 'Аллергены не указаны';
    const link = document.createElement('a'); link.className = 'catalog-open-button'; link.href = `product.html?item=${product.id}`; link.innerHTML = 'Открыть состав <span aria-hidden="true">→</span>';
    body.append(heading, description, allergenNote, link);
    card.append(art, body); grid.append(card);
  });
}

async function loadCatalog() {
  try {
    const products = await YaVizhuAPI.request('/api/products');
    renderProducts(products);
    count.textContent = products.length;
    count.setAttribute('aria-label', `Товаров в подборке: ${products.length}`);
    status.textContent = products.length ? '' : 'В каталоге пока нет товаров.';
  } catch (error) { status.textContent = error.message; }
}

loadCatalog();
