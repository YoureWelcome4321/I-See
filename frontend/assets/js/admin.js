const loginPanel = document.querySelector('#admin-login-panel');
const dashboard = document.querySelector('#admin-dashboard');
const loginForm = document.querySelector('#admin-login-form');
const loginStatus = document.querySelector('#admin-login-status');
const productForm = document.querySelector('#admin-product-form');
const productStatus = document.querySelector('#admin-product-status');
const productList = document.querySelector('#admin-product-list');
const sectionElements = {
  products: document.querySelector('#admin-section-products'),
  stories: document.querySelector('#admin-section-stories'),
  recipes: document.querySelector('#admin-section-recipes'),
};
const tabs = [...document.querySelectorAll('[data-admin-tab]')];
const storyForm = document.querySelector('#admin-story-form');
const storyStatus = document.querySelector('#admin-story-status');
const storyList = document.querySelector('#admin-story-list');
const storyCancel = document.querySelector('#admin-story-cancel');
const storyModal = document.querySelector('#admin-story-modal');
const storyAdd = document.querySelector('#admin-story-add');
const storyModalTitle = document.querySelector('#admin-story-modal-title');
const productModal = document.querySelector('#admin-product-modal');
const productAdd = document.querySelector('#admin-product-add');
const productCancel = document.querySelector('#admin-product-cancel');
const productModalTitle = document.querySelector('#admin-product-modal-title');
function showDashboard(user) {
  const isAdmin = Boolean(user?.is_admin);
  loginPanel.hidden = isAdmin;
  dashboard.hidden = !isAdmin;
  if (isAdmin) {
    showSection('products');
    loadProducts();
  }
}

function showSection(name) {
  for (const [sectionName, section] of Object.entries(sectionElements)) {
    if (section) section.hidden = sectionName !== name;
  }
  tabs.forEach((tab) => tab.setAttribute('aria-pressed', String(tab.dataset.adminTab === name)));
  if (name === 'stories') loadStories();
  if (name === 'recipes') loadRecipes();
}

async function loadRecipes() {
  const list = document.querySelector('#admin-recipe-list'); const status = document.querySelector('#admin-recipe-status');
  try { const recipes = await YaVizhuAPI.request('/api/admin/recipes'); document.querySelector('#admin-recipe-count').textContent = recipes.length; list.replaceChildren(); recipes.forEach((recipe) => { const row=document.createElement('article'); row.className='admin-product-row'; const info=document.createElement('div'); const title=document.createElement('h3'); title.textContent=recipe.title; const detail=document.createElement('p'); detail.textContent=`${recipe.ingredients.length} ингредиентов${recipe.sponsored_product ? ` · ${recipe.sponsored_label || 'Реклама'}: ${recipe.sponsored_product}` : ''}`; info.append(title,detail); const remove=document.createElement('button'); remove.className='catalog-remove'; remove.type='button'; remove.textContent='Удалить'; remove.onclick=async()=>{ if(!confirm(`Удалить рецепт «${recipe.title}»?`)) return; await YaVizhuAPI.request(`/api/admin/recipes/${encodeURIComponent(recipe.id)}`,{method:'DELETE'}); loadRecipes(); }; row.append(info,remove); list.append(row); }); } catch (error) { status.textContent=error.message; }
}

function renderProducts(products) {
  productList.replaceChildren();
  if (!products.length) {
    productList.textContent = 'В каталоге пока нет товаров.';
    return;
  }

  products.forEach((product) => {
    const row = document.createElement('article');
    row.className = 'admin-product-row';
    const info = document.createElement('div');
    const title = document.createElement('h3');
    title.textContent = product.name;
    const detail = document.createElement('p');
    detail.textContent = `${product.category || 'Продукты'} · ${product.price ? `${product.price} ₽` : 'Цена не указана'}${product.barcode ? ` · Штрихкод ${product.barcode}` : ''}`;
    info.append(title, detail);

    const remove = document.createElement('button');
    remove.className = 'catalog-remove';
    remove.type = 'button';
    remove.textContent = 'Удалить';
    remove.addEventListener('click', async () => {
      if (!window.confirm(`Удалить товар «${product.name}»?`)) return;
      try {
        await YaVizhuAPI.request(`/api/products/${product.id}`, { method: 'DELETE' });
        productStatus.textContent = 'Товар удалён.';
        await loadProducts();
      } catch (error) {
        productStatus.textContent = error.message;
      }
    });
    const actions = document.createElement('div');
    actions.className = 'admin-product-row-actions';
    const edit = document.createElement('button');
    edit.className = 'ui-btn ui-btn--ghost ui-btn--sm';
    edit.type = 'button';
    edit.textContent = 'Изменить';
    edit.addEventListener('click', () => openProductModal(product));
    actions.append(edit, remove);
    row.append(info, actions);
    productList.append(row);
  });
}

async function loadProducts() {
  try {
    const products = await YaVizhuAPI.request('/api/products');
    renderProducts(products);
  } catch (error) {
    productStatus.textContent = error.message;
  }
}

function renderUsers(users) {
  userList.replaceChildren();
  if (!users.length) {
    userList.textContent = 'Пользователей пока нет.';
    return;
  }
  users.forEach((user) => {
    const row = document.createElement('article');
    row.className = 'admin-product-row';
    const info = document.createElement('div');
    const title = document.createElement('h3');
    title.textContent = user.name;
    const detail = document.createElement('p');
    detail.textContent = `Логин: ${user.login} · ${user.is_admin ? 'Администратор' : 'Пользователь'} · Проверок: ${user.checks_count}`;
    info.append(title, detail);
    row.append(info);
    userList.append(row);
  });
}

async function loadUsers() {
  try {
    renderUsers(await YaVizhuAPI.request('/api/admin/users'));
  } catch (error) {
    userStatus.textContent = error.message;
  }
}

function renderStories(stories) {
  storyList.replaceChildren();
  if (!stories.length) {
    storyList.textContent = 'Историй пока нет. Добавьте первую с помощью формы выше.';
    return;
  }
  stories.forEach((story) => {
    const row = document.createElement('article');
    row.className = 'admin-story-row';
    const image = document.createElement('img');
    image.src = `/assets/images/${story.image}`;
    image.alt = '';
    const info = document.createElement('div');
    info.className = 'admin-story-row-copy';
    const title = document.createElement('h3');
    title.textContent = story.title;
    const detail = document.createElement('p');
    detail.textContent = `${story.subtitle || 'Без подписи'} · ${story.href}`;
    info.append(title, detail);
    const actions = document.createElement('div');
    actions.className = 'admin-story-row-actions';
    const edit = document.createElement('button');
    edit.className = 'ui-btn ui-btn--ghost ui-btn--sm';
    edit.type = 'button';
    edit.textContent = 'Изменить';
    edit.addEventListener('click', () => {
      storyForm.elements.id.value = story.id;
      storyForm.elements.title.value = story.title;
      storyForm.elements.subtitle.value = story.subtitle;
      storyForm.elements.image.value = story.image;
      openStoryModal(story);
    });
    const remove = document.createElement('button');
    remove.className = 'catalog-remove';
    remove.type = 'button';
    remove.textContent = 'Удалить';
    if (story.id === 'story-how' || story.id === 'story-team') {
      remove.disabled = true;
      remove.title = 'Системную историю нельзя удалить';
    }
    remove.addEventListener('click', async () => {
      if (!window.confirm(`Удалить историю «${story.title}»?`)) return;
      try {
        await YaVizhuAPI.request(`/api/admin/stories/${encodeURIComponent(story.id)}`, { method: 'DELETE' });
        storyStatus.textContent = 'История удалена.';
        await loadStories();
      } catch (error) {
        storyStatus.textContent = error.message;
      }
    });
    actions.append(edit, remove);
    row.append(image, info, actions);
    storyList.append(row);
  });
}

async function loadStories() {
  try {
    renderStories(await YaVizhuAPI.request('/api/admin/stories'));
  } catch (error) {
    storyStatus.textContent = error.message;
  }
}

async function loadStoryRecipeOptions(selectedId = '') {
  const select = document.querySelector('#admin-story-recipe');
  const recipes = await YaVizhuAPI.request('/api/admin/recipes');
  select.replaceChildren(new Option('Информационная история без рецепта', ''));
  recipes.forEach((recipe) => select.add(new Option(recipe.title, recipe.id)));
  select.value = selectedId || '';
}

loginForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  loginStatus.textContent = 'Проверяем доступ…';
  const formData = new FormData(loginForm);
  try {
    const user = await YaVizhuAPI.login(formData.get('login').trim(), formData.get('password'));
    if (!user.is_admin) {
      YaVizhuAPI.logout();
      loginStatus.textContent = 'У этой учётной записи нет прав администратора.';
      return;
    }
    loginStatus.textContent = '';
    showDashboard(user);
  } catch (error) {
    loginStatus.textContent = error.message;
  }
});

tabs.forEach((tab) => tab.addEventListener('click', () => showSection(tab.dataset.adminTab)));

async function openStoryModal(story = null) {
  storyForm.reset();
  storyForm.elements.id.value = story?.id || '';
  storyForm.elements.title.value = story?.title || '';
  storyForm.elements.subtitle.value = story?.subtitle || '';
  storyForm.elements.image.value = story?.image || 'story-01.jpg';
  storyForm.elements.recipe_id.value = story?.recipe_id || '';
  storyModalTitle.textContent = story ? 'Изменить историю' : 'Новая история';
  storyModal.hidden = false;
  try { await loadStoryRecipeOptions(story?.recipe_id || ''); } catch (error) { storyStatus.textContent = error.message; }
  storyForm.elements.title.focus();
}

function closeStoryModal() {
  storyModal.hidden = true;
}

function resetStoryForm() {
  storyForm.reset();
  storyForm.elements.id.value = '';
  closeStoryModal();
}

storyAdd.addEventListener('click', () => openStoryModal());
storyCancel.addEventListener('click', resetStoryForm);
storyModal.querySelectorAll('[data-admin-story-modal-close]').forEach((element) => element.addEventListener('click', closeStoryModal));

storyForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(storyForm));
  try {
    await YaVizhuAPI.request('/api/admin/stories', { method: 'POST', body: JSON.stringify(data) });
    resetStoryForm();
    storyStatus.textContent = data.id ? 'История обновлена.' : 'История добавлена.';
    await loadStories();
  } catch (error) {
    storyStatus.textContent = error.message;
  }
});

function openProductModal(product = null) {
  productForm.reset();
  productForm.elements.id.value = product?.id || '';
  productForm.elements.name.value = product?.name || '';
  productForm.elements.category.value = product?.category || 'Продукты';
  productForm.elements.barcode.value = product?.barcode || '';
  productForm.elements.allergens.value = product?.allergens || '';
  productForm.elements.ingredients.value = product?.ingredients || '';
  productForm.elements.price.value = product?.price || 0;
  productModalTitle.textContent = product ? 'Изменить товар' : 'Новый товар';
  productModal.hidden = false;
  productForm.elements.name.focus();
}

function closeProductModal() {
  productModal.hidden = true;
}

productAdd.addEventListener('click', () => openProductModal());
productCancel.addEventListener('click', closeProductModal);
productModal.querySelectorAll('[data-admin-modal-close]').forEach((element) => element.addEventListener('click', closeProductModal));

productForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(productForm));
  data.price = Number(data.price || 0);
  try {
    const id = data.id;
    delete data.id;
    await YaVizhuAPI.request(id ? `/api/products/${id}` : '/api/products', { method: id ? 'PUT' : 'POST', body: JSON.stringify(data) });
    closeProductModal();
    productStatus.textContent = id ? 'Товар обновлён.' : 'Товар добавлен.';
    await loadProducts();
  } catch (error) {
    productStatus.textContent = error.message;
  }
});

document.querySelector('#admin-logout').addEventListener('click', () => {
  YaVizhuAPI.logout();
  dashboard.hidden = true;
  loginPanel.hidden = false;
  loginForm.reset();
  loginStatus.textContent = 'Вы вышли из панели администратора.';
});

const savedUser = YaVizhuAPI.getUser();
if (savedUser?.is_admin) {
  showDashboard(savedUser);
} else if (savedUser) {
  loginStatus.textContent = 'Войдите под учётной записью администратора.';
}
