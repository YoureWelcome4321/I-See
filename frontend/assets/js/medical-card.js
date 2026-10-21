const storageKey = 'ya-vizhu-medical-card-v1';
const onboardingStorageKey = 'ya-vizhu-onboarding-restrictions';
const fontSizeKey = 'ya-vizhu-font-size';
const form = document.querySelector('#medical-form');
const foodName = document.querySelector('#food-name');
const list = document.querySelector('#medical-list');
const status = document.querySelector('#medical-status');
const accountName = document.querySelector('#account-name');
const accountPhone = document.querySelector('#account-phone');
const accountInitial = document.querySelector('#account-initial');
const logoutButton = document.querySelector('#logout-button');
const sizeButtons = document.querySelectorAll('.profile-size [data-font-size]');
const loginUrl = '/login.html?next=/medical-card.html';

function normalizeItems(value) {
  if (!Array.isArray(value)) return [];
  const seen = new Set();
  return value.reduce((result, item) => {
    if (!item || !['allergy', 'avoid'].includes(item.type)) return result;
    const name = String(item.name || item.food || '').trim().slice(0, 80);
    if (!name) return result;
    const key = `${item.type}:${name.toLocaleLowerCase('ru')}`;
    if (seen.has(key)) return result;
    seen.add(key);
    result.push({ name, type: item.type });
    return result;
  }, []);
}

function parseItems(raw) {
  try { return normalizeItems(JSON.parse(raw || '[]')); } catch { return []; }
}

function readItems() {
  const stored = localStorage.getItem(storageKey);
  if (stored !== null) return parseItems(stored);
  const legacy = parseItems(localStorage.getItem(onboardingStorageKey));
  if (legacy.length) localStorage.setItem(storageKey, JSON.stringify(legacy));
  return legacy;
}

let items = readItems();

function saveItems() {
  try {
    localStorage.setItem(storageKey, JSON.stringify(items));
    YaVizhuAPI.request('/api/profile', { method: 'POST', body: JSON.stringify({ restrictions: items }) })
      .catch(() => { status.textContent = 'Список сохранён на телефоне, но не отправился на сервер. Проверьте интернет.'; });
    return true;
  } catch {
    status.textContent = 'Не получилось сохранить список на этом телефоне.';
    return false;
  }
}

function formatPhone(phone) {
  const digits = String(phone || '').replace(/\D/g, '');
  if (digits.length !== 11) return phone || '';
  return `+7 ${digits.slice(1, 4)} ${digits.slice(4, 7)}-${digits.slice(7, 9)}-${digits.slice(9)}`;
}

function updateAccount() {
  const user = YaVizhuAPI.getUser() || {};
  const name = (user.name || '').trim() || 'Ваш профиль';
  accountName.textContent = user.name ? `Здравствуйте, ${name}!` : name;
  accountInitial.textContent = name.charAt(0).toLocaleUpperCase('ru');
  accountPhone.textContent = formatPhone(user.phone);
  accountPhone.hidden = !user.phone;
}

// For a signed-in user the server list is the source of truth; this also catches an expired session.
async function syncFromServer() {
  try {
    const result = await YaVizhuAPI.request('/api/profile');
    items = normalizeItems(result.restrictions);
    localStorage.setItem(storageKey, JSON.stringify(items));
    renderItems();
  } catch {
    if (!YaVizhuAPI.hasToken()) window.location.replace(`${loginUrl}&expired=1`);
  }
}

logoutButton.addEventListener('click', () => {
  YaVizhuAPI.logout();
  window.location.assign('/');
});

function renderItems() {
  list.replaceChildren();
  if (!items.length) {
    const empty = document.createElement('li');
    empty.className = 'profile-empty';
    empty.textContent = 'Список пока пуст.';
    list.append(empty);
    return;
  }
  items.forEach((item, index) => {
    const row = document.createElement('li');
    row.className = `profile-item is-${item.type}`;
    const description = document.createElement('span');
    const category = document.createElement('small');
    category.textContent = item.type === 'allergy' ? 'Аллергия' : 'Не ем';
    description.append(category, document.createTextNode(item.name));
    const remove = document.createElement('button');
    remove.className = 'ui-btn ui-btn--danger ui-btn--sm';
    remove.type = 'button';
    remove.textContent = 'Убрать';
    remove.setAttribute('aria-label', `Убрать «${item.name}» из списка`);
    remove.addEventListener('click', () => {
      items.splice(index, 1);
      saveItems();
      status.textContent = `«${item.name}» убран из списка.`;
      renderItems();
    });
    row.append(description, remove);
    list.append(row);
  });
}

// Two submit buttons answer "why" in one tap instead of a separate dropdown.
form.addEventListener('submit', (event) => {
  event.preventDefault();
  const type = event.submitter?.value === 'avoid' ? 'avoid' : 'allergy';
  const name = foodName.value.trim();
  if (!name) {
    status.textContent = 'Сначала напишите название продукта.';
    foodName.focus();
    return;
  }
  if (items.some((item) => item.name.toLocaleLowerCase('ru') === name.toLocaleLowerCase('ru') && item.type === type)) {
    status.textContent = `«${name}» уже есть в списке.`;
    foodName.focus();
    return;
  }
  items.push({ name, type });
  if (saveItems()) status.textContent = `«${name}» добавлен в список.`;
  renderItems();
  foodName.value = '';
  foodName.focus();
});

function applyFontSize(size) {
  document.documentElement.dataset.fontSize = size;
  sizeButtons.forEach((button) => button.setAttribute('aria-pressed', String(button.dataset.fontSize === size)));
}

sizeButtons.forEach((button) => button.addEventListener('click', () => {
  try { localStorage.setItem(fontSizeKey, button.dataset.fontSize); } catch { /* the size still applies to this visit */ }
  applyFontSize(button.dataset.fontSize);
}));

// The profile is for signed-in people only; guests sign in on their own page.
if (!YaVizhuAPI.hasToken()) {
  window.location.replace(loginUrl);
} else {
  applyFontSize(localStorage.getItem(fontSizeKey) === 'large' ? 'large' : 'normal');
  renderItems();
  updateAccount();
  syncFromServer();
}
