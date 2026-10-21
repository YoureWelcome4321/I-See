const loginPanel = document.querySelector('#admin-login-panel');
const dashboard = document.querySelector('#admin-dashboard');
const loginForm = document.querySelector('#admin-login-form');
const loginStatus = document.querySelector('#admin-login-status');
const productForm = document.querySelector('#admin-product-form');
const productStatus = document.querySelector('#admin-product-status');
const productList = document.querySelector('#admin-product-list');
const recipeList = document.querySelector('#admin-recipe-list');
const recipeStatus = document.querySelector('#admin-recipe-status');
const userList = document.querySelector('#admin-user-list');
const userStatus = document.querySelector('#admin-user-status');
const sectionElements = {
  products: document.querySelector('#admin-section-products'),
  recipes: document.querySelector('#admin-section-recipes'),
  stories: document.querySelector('#admin-section-stories'),
  users: document.querySelector('#admin-section-users'),
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
const SYSTEM_STORIES = ['story-how', 'story-team'];
const STORY_KIND_NAMES = { article: 'Статья', recipe: 'Рецепт', guide: 'Инструкция' };
const ICONS = {
  edit: '<svg viewBox="0 0 24 24"><path d="M4 20h4L19 9l-4-4L4 16v4Z"></path><path d="m13.5 6.5 4 4"></path></svg>',
  trash: '<svg viewBox="0 0 24 24"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"></path></svg>',
  lock: '<svg viewBox="0 0 24 24"><rect x="5" y="11" width="14" height="9" rx="3"></rect><path d="M8 11V8a4 4 0 0 1 8 0v3"></path></svg>',
};

// ---------- Small building blocks for every list ----------
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function tag(text, variant = '') {
  return el('span', `admin-tag${variant ? ` admin-tag--${variant}` : ''}`, text);
}

function iconButton(icon, label, onClick, danger = false) {
  const button = el('button', `admin-icon-btn${danger ? ' admin-icon-btn--danger' : ''}`);
  button.type = 'button';
  button.innerHTML = ICONS[icon];
  button.setAttribute('aria-label', label);
  button.title = label;
  if (onClick) button.addEventListener('click', onClick);
  return button;
}

function row({ mark, image, title, tags, actions, search }) {
  const node = el('article', 'admin-row');
  node.dataset.search = search.toLocaleLowerCase('ru');
  if (image) { const img = el('img', 'admin-row-thumb'); img.src = image; img.alt = ''; img.loading = 'lazy'; node.append(img); }
  else node.append(el('span', 'admin-row-mark', mark));
  const main = el('div', 'admin-row-main');
  const tagBox = el('div', 'admin-tags');
  tagBox.append(...tags);
  main.append(el('h4', '', title), tagBox);
  const actionBox = el('div', 'admin-row-actions');
  actionBox.append(...actions);
  node.append(main, actionBox);
  return node;
}

function showEmpty(list, text) {
  list.replaceChildren(el('p', 'admin-empty', text));
}

function setStatus(node, text, isError = false) {
  node.textContent = text;
  node.classList.toggle('is-error', isError);
}

function setCount(key, value) {
  document.querySelector(`[data-count="${key}"]`).textContent = value;
}

// The search box above a list hides rows that do not contain the typed words.
document.querySelectorAll('[data-filter]').forEach((input) => input.addEventListener('input', () => {
  const query = input.value.trim().toLocaleLowerCase('ru');
  const list = sectionElements[input.dataset.filter].querySelector('.admin-list');
  list.querySelectorAll('[data-search]').forEach((item) => { item.hidden = Boolean(query) && !item.dataset.search.includes(query); });
}));

function showDashboard(user) {
  const isAdmin = Boolean(user?.is_admin);
  loginPanel.hidden = isAdmin;
  dashboard.hidden = !isAdmin;
  if (!isAdmin) return;
  document.querySelector('#admin-avatar').textContent = (user.name || 'А').trim().charAt(0).toLocaleUpperCase('ru');
  showSection('products');
  // The other tiles show their counts right away, without opening each section.
  loadRecipes(); loadStories(); loadUsers();
}

function showSection(name) {
  for (const [sectionName, section] of Object.entries(sectionElements)) section.hidden = sectionName !== name;
  tabs.forEach((tab) => tab.setAttribute('aria-pressed', String(tab.dataset.adminTab === name)));
  ({ products: loadProducts, recipes: loadRecipes, stories: loadStories, users: loadUsers })[name]();
}

// ---------- Products ----------
function renderProducts(products) {
  setCount('products', products.length);
  if (!products.length) { showEmpty(productList, 'В каталоге пока нет товаров. Добавьте первый.'); return; }
  productList.replaceChildren(...products.map((product) => {
    const tags = [tag(product.category || 'Продукты', 'green'), tag(product.price ? `${product.price} ₽` : 'Цена не указана')];
    if (product.barcode) tags.push(tag(`Штрихкод ${product.barcode}`));
    if (product.allergens) tags.push(tag(`Аллергены: ${product.allergens}`, 'danger'));
    const remove = async () => {
      if (!window.confirm(`Удалить товар «${product.name}»?`)) return;
      try {
        await YaVizhuAPI.request(`/api/products/${product.id}`, { method: 'DELETE' });
        setStatus(productStatus, `Товар «${product.name}» удалён.`);
        await loadProducts();
      } catch (error) { setStatus(productStatus, error.message, true); }
    };
    return row({
      mark: product.name.charAt(0).toLocaleUpperCase('ru'),
      title: product.name,
      tags,
      search: `${product.name} ${product.category} ${product.barcode} ${product.ingredients} ${product.allergens}`,
      actions: [iconButton('edit', `Изменить «${product.name}»`, () => openProductModal(product)), iconButton('trash', `Удалить «${product.name}»`, remove, true)],
    });
  }));
}

async function loadProducts() {
  try { renderProducts(await YaVizhuAPI.request('/api/products')); }
  catch (error) { setStatus(productStatus, error.message, true); }
}

// ---------- Recipes ----------
async function loadRecipes() {
  try {
    const recipes = await YaVizhuAPI.request('/api/admin/recipes');
    setCount('recipes', recipes.length);
    if (!recipes.length) { showEmpty(recipeList, 'Рецептов пока нет.'); return; }
    recipeList.replaceChildren(...recipes.map((recipe) => {
      const tags = [tag(`${recipe.ingredients.length} ${recipe.ingredients.length === 1 ? 'ингредиент' : 'ингредиентов'}`, 'green')];
      if (recipe.sponsored_product) tags.push(tag(`${recipe.sponsored_label || 'Реклама'}: ${recipe.sponsored_product}`, 'lime'));
      const remove = async () => {
        if (!window.confirm(`Удалить рецепт «${recipe.title}»?`)) return;
        try {
          await YaVizhuAPI.request(`/api/admin/recipes/${encodeURIComponent(recipe.id)}`, { method: 'DELETE' });
          setStatus(recipeStatus, `Рецепт «${recipe.title}» удалён.`);
          await loadRecipes();
        } catch (error) { setStatus(recipeStatus, error.message, true); }
      };
      return row({
        image: `/assets/images/${recipe.image}`,
        title: recipe.title,
        tags,
        search: `${recipe.title} ${recipe.ingredients.join(' ')}`,
        actions: [iconButton('trash', `Удалить «${recipe.title}»`, remove, true)],
      });
    }));
  } catch (error) { setStatus(recipeStatus, error.message, true); }
}

// ---------- Users ----------
async function loadUsers() {
  try {
    const users = await YaVizhuAPI.request('/api/admin/users');
    setCount('users', users.length);
    if (!users.length) { showEmpty(userList, 'Пользователей пока нет.'); return; }
    userList.replaceChildren(...users.map((user) => {
      const tags = [user.is_admin ? tag('Администратор', 'dark') : tag('Пользователь', 'green')];
      if (user.phone) tags.push(tag(user.phone));
      tags.push(tag(`Проверок: ${user.checks_count}`));
      return row({
        mark: (user.name || '?').trim().charAt(0).toLocaleUpperCase('ru'),
        title: user.name || user.login,
        tags,
        search: `${user.name} ${user.phone} ${user.login}`,
        actions: [],
      });
    }));
  } catch (error) { setStatus(userStatus, error.message, true); }
}

// ---------- Stories ----------
function renderStories(stories) {
  setCount('stories', stories.length);
  if (!stories.length) { showEmpty(storyList, 'Историй пока нет. Добавьте первую.'); return; }
  storyList.replaceChildren(...stories.map((story) => {
    const system = SYSTEM_STORIES.includes(story.id);
    const card = el('article', 'admin-story-card');
    const cover = el('div', 'admin-story-cover');
    const image = el('img'); image.src = `/assets/images/${story.image}`; image.alt = ''; image.loading = 'lazy';
    const badges = el('div', 'admin-tags');
    badges.append(tag(STORY_KIND_NAMES[story.kind] || STORY_KIND_NAMES.article, 'lime'));
    if (system) badges.append(tag('Системная', 'dark'));
    if (story.kind !== 'recipe' && !story.body) badges.append(tag('Без текста', 'danger'));
    cover.append(image, badges);
    const body = el('div', 'admin-story-body');
    body.append(el('h4', '', story.title), el('p', '', story.subtitle || 'Без подписи'));
    const foot = el('div', 'admin-story-foot');
    if (system) {
      const locked = iconButton('lock', 'Системную историю нельзя изменить или удалить');
      locked.disabled = true;
      foot.append(locked);
    } else {
      const remove = async () => {
        if (!window.confirm(`Удалить историю «${story.title}»?`)) return;
        try {
          await YaVizhuAPI.request(`/api/admin/stories/${encodeURIComponent(story.id)}`, { method: 'DELETE' });
          setStatus(storyStatus, `История «${story.title}» удалена.`);
          await loadStories();
        } catch (error) { setStatus(storyStatus, error.message, true); }
      };
      foot.append(iconButton('edit', `Изменить «${story.title}»`, () => openStoryModal(story)), iconButton('trash', `Удалить «${story.title}»`, remove, true));
    }
    card.append(cover, body, foot);
    return card;
  }));
}

async function loadStories() {
  try { renderStories(await YaVizhuAPI.request('/api/admin/stories')); }
  catch (error) { setStatus(storyStatus, error.message, true); }
}

const storyRecipeImages = new Map();
const storyFile = document.querySelector('#admin-story-file');
const storyPreview = document.querySelector('#admin-story-preview');
const storyPhotoHint = document.querySelector('#admin-story-photo-hint');
const storyFileLabel = document.querySelector('#admin-story-file-label');

async function loadStoryRecipeOptions(selectedId = '') {
  const select = document.querySelector('#admin-story-recipe');
  const recipes = await YaVizhuAPI.request('/api/admin/recipes');
  select.replaceChildren(new Option('Информационная история без рецепта', ''));
  storyRecipeImages.clear();
  recipes.forEach((recipe) => { select.add(new Option(recipe.title, recipe.id)); storyRecipeImages.set(recipe.id, recipe.image); });
  select.value = selectedId || '';
  updateStoryPhoto();
}

const STORY_BODY_TEXT = {
  article: ['Текст статьи', 'Абзацы отделяйте пустой строкой. Пишите коротко и простыми словами.'],
  guide: ['Шаги инструкции', 'Каждый шаг — с новой строки, они будут пронумерованы.'],
};

// What is inside the story decides which fields make sense: a recipe or text.
function updateStoryKind() {
  const kind = storyForm.elements.kind.value;
  const isRecipe = kind === 'recipe';
  document.querySelector('#admin-story-recipe-field').hidden = !isRecipe;
  document.querySelector('#admin-story-body-field').hidden = isRecipe;
  document.querySelector('#admin-story-photo-recipe').hidden = !isRecipe;
  if (!isRecipe) {
    storyForm.elements.recipe_id.value = '';
    storyForm.elements.photo_source.value = 'upload';
    const [label, hint] = STORY_BODY_TEXT[kind];
    document.querySelector('#admin-story-body-label').textContent = label;
    document.querySelector('#admin-story-body-hint').textContent = hint;
  }
  updateStoryPhoto();
}

// The photo is either uploaded by the admin or taken live from the chosen recipe.
function updateStoryPhoto() {
  const fromRecipe = storyForm.elements.photo_source.value === 'recipe';
  const recipeImage = storyRecipeImages.get(storyForm.elements.recipe_id.value);
  const image = fromRecipe ? recipeImage : storyForm.elements.image.value;
  storyFileLabel.hidden = fromRecipe;
  storyPreview.hidden = !image;
  if (image) storyPreview.src = `/assets/images/${image}`;
  if (fromRecipe) storyPhotoHint.textContent = recipeImage ? 'Фото подставится из рецепта и будет меняться вместе с ним.' : 'Выберите рецепт выше — фото возьмётся из него.';
  else storyPhotoHint.textContent = image ? 'Можно выбрать другой файл, чтобы заменить фото.' : 'JPEG, PNG или WebP до 5 МБ.';
}

storyForm.elements.photo_source.forEach((radio) => radio.addEventListener('change', updateStoryPhoto));
storyForm.elements.kind.forEach((radio) => radio.addEventListener('change', updateStoryKind));
storyForm.elements.recipe_id.addEventListener('change', updateStoryPhoto);
storyFile.addEventListener('change', async () => {
  const file = storyFile.files[0];
  if (!file) return;
  storyPhotoHint.textContent = 'Загружаем фото…';
  try {
    const { image } = await YaVizhuAPI.request('/api/admin/uploads', { method: 'POST', body: file, headers: { 'Content-Type': file.type || 'application/octet-stream' } });
    storyForm.elements.image.value = image;
    updateStoryPhoto();
  } catch (error) {
    storyPhotoHint.textContent = error.message;
  } finally {
    storyFile.value = '';
  }
});

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
  const fromRecipe = story?.photo_source === 'recipe';
  storyForm.elements.photo_source.value = fromRecipe ? 'recipe' : 'upload';
  storyForm.elements.image.value = story && !fromRecipe ? story.image : '';
  storyForm.elements.recipe_id.value = story?.recipe_id || '';
  storyForm.elements.kind.value = story?.kind || 'article';
  storyForm.elements.body.value = story?.body || '';
  updateStoryKind();
  storyModalTitle.textContent = story ? 'Изменить историю' : 'Новая история';
  storyModal.hidden = false;
  try { await loadStoryRecipeOptions(story?.recipe_id || ''); } catch (error) { setStatus(storyStatus, error.message, true); }
  updateStoryKind();
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
  const { photo_source: photoSource, ...data } = Object.fromEntries(new FormData(storyForm));
  if (data.kind === 'recipe' && !data.recipe_id) { storyPhotoHint.textContent = 'Выберите рецепт для этой истории.'; storyForm.elements.recipe_id.focus(); return; }
  if (data.kind !== 'recipe' && !data.body.trim()) { storyForm.elements.body.focus(); document.querySelector('#admin-story-body-hint').textContent = 'Напишите текст — без него история будет пустой.'; return; }
  if (data.kind !== 'recipe') data.recipe_id = '';
  if (photoSource === 'recipe') data.image = '';
  if (photoSource === 'recipe' && !data.recipe_id) { storyPhotoHint.textContent = 'Выберите рецепт, чтобы взять фото из него.'; return; }
  if (photoSource === 'upload' && !data.image) { storyPhotoHint.textContent = 'Загрузите фото для истории.'; return; }
  try {
    await YaVizhuAPI.request('/api/admin/stories', { method: 'POST', body: JSON.stringify(data) });
    resetStoryForm();
    setStatus(storyStatus, data.id ? 'История обновлена.' : 'История добавлена.');
    await loadStories();
  } catch (error) {
    setStatus(storyStatus, error.message, true);
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
    setStatus(productStatus, id ? 'Товар обновлён.' : 'Товар добавлен.');
    await loadProducts();
  } catch (error) {
    setStatus(productStatus, error.message, true);
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
