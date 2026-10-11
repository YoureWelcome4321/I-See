const storageKey = 'ya-vizhu-medical-card-v1';
const form = document.querySelector('#medical-form');
const foodName = document.querySelector('#food-name');
const foodType = document.querySelector('#food-type');
const list = document.querySelector('#medical-list');
const status = document.querySelector('#medical-status');
const loginForm = document.querySelector('#login-form');
const loginStatus = document.querySelector('#login-status');
const loginName = document.querySelector('#login-name');
const loginPassword = document.querySelector('#login-password');
const accountName = document.querySelector('#account-name');
const logoutButton = document.querySelector('#logout-button');
const historyList = document.querySelector('#check-history');
const historyStatus = document.querySelector('#history-status');

function readItems() {
  try {
    const value = JSON.parse(localStorage.getItem(storageKey) || '[]');
    return Array.isArray(value) ? value.filter((item) => item && typeof item.name === 'string' && ['allergy', 'avoid'].includes(item.type)) : [];
  } catch {
    return [];
  }
}

let items = readItems();

function saveItems() {
  try {
    localStorage.setItem(storageKey, JSON.stringify(items));
    if (YaVizhuAPI.hasToken()) {
      YaVizhuAPI.request('/api/profile', { method: 'POST', body: JSON.stringify({ restrictions: items }) })
        .catch(() => { status.textContent = 'Список сохранён на устройстве, но не удалось синхронизировать его с сервером.'; });
    }
    return true;
  } catch {
    status.textContent = 'Не удалось сохранить список на этом устройстве.';
    return false;
  }
}

async function loadHistory() {
  if (!YaVizhuAPI.hasToken()) {
    historyStatus.textContent = 'Войдите, чтобы увидеть историю проверок.';
    historyList.replaceChildren();
    return;
  }
  try {
    const history = await YaVizhuAPI.request('/api/checks');
    historyList.replaceChildren();
    if (!history.length) {
      historyStatus.textContent = 'Сохранённых проверок пока нет. Отсканируйте продукт и нажмите «Сохранить проверку». ';
      return;
    }
    historyStatus.textContent = `Сохранено проверок: ${history.length}.`;
    [...history].reverse().forEach((entry) => {
      const row = document.createElement('li'); row.className = 'medical-item';
      const text = document.createElement('span');
      const title = document.createElement('strong'); title.textContent = entry.product_name;
      const detail = document.createElement('small');
      const date = new Date(entry.checked_at).toLocaleString('ru-RU');
      const outcome = entry.result === 'warning' ? `Есть совпадение: ${entry.matches.join(', ')}` : entry.result === 'clear' ? 'Совпадений с карточкой нет' : entry.reason === 'no_restrictions' ? 'Добавьте ограничения для сравнения' : 'Недостаточно данных о составе';
      detail.textContent = `${date} · ${outcome}`;
      text.append(title, document.createElement('br'), detail);
      row.append(text); historyList.append(row);
    });
  } catch (error) { historyStatus.textContent = error.message; }
}

function updateAccount() {
  const user = YaVizhuAPI.getUser();
  accountName.textContent = user ? `Вы вошли как ${user.name}` : 'Гостевой режим';
  logoutButton.hidden = !user;
  loginForm.hidden = Boolean(user);
  loadHistory();
}

loginForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  loginStatus.textContent = 'Выполняется вход…';
  try {
    const localItems = items;
    const user = await YaVizhuAPI.login(loginName.value.trim(), loginPassword.value);
    let result = await YaVizhuAPI.request('/api/profile');
    if (!result.restrictions.length && localItems.length) {
      result = await YaVizhuAPI.request('/api/profile', { method: 'POST', body: JSON.stringify({ restrictions: localItems }) });
    }
    items = result.restrictions;
    localStorage.setItem(storageKey, JSON.stringify(items));
    renderItems();
    loginStatus.textContent = `Здравствуйте, ${user.name}. Вход выполнен.`;
    loginPassword.value = '';
    updateAccount();
  } catch (error) { loginStatus.textContent = error.message; }
});

logoutButton.addEventListener('click', () => {
  YaVizhuAPI.logout();
  loginStatus.textContent = 'Вы вышли из профиля.';
  updateAccount();
});

function renderItems() {
  list.replaceChildren();
  if (!items.length) {
    const empty = document.createElement('li');
    empty.className = 'medical-empty';
    empty.textContent = 'Пока список пуст. Добавьте продукт, если хотите.';
    list.append(empty);
    return;
  }

  items.forEach((item, index) => {
    const row = document.createElement('li');
    row.className = 'medical-item';
    const description = document.createElement('span');
    const category = document.createElement('strong');
    category.textContent = item.type === 'allergy' ? 'Аллергия: ' : 'Не ем: ';
    description.append(category, document.createTextNode(item.name));
    const remove = document.createElement('button');
    remove.className = 'medical-remove';
    remove.type = 'button';
    remove.textContent = 'Убрать';
    remove.setAttribute('aria-label', `Убрать ${item.name} из карточки`);
    remove.addEventListener('click', () => {
      items.splice(index, 1);
      saveItems();
      status.textContent = `Запись «${item.name}» удалена.`;
      renderItems();
    });
    row.append(description, remove);
    list.append(row);
  });
}

form.addEventListener('submit', (event) => {
  event.preventDefault();
  const name = foodName.value.trim();
  if (!name) {
    foodName.focus();
    status.textContent = 'Введите название продукта.';
    return;
  }
  const duplicate = items.some((item) => item.name.toLocaleLowerCase('ru') === name.toLocaleLowerCase('ru') && item.type === foodType.value);
  if (duplicate) {
    status.textContent = `«${name}» уже есть в списке.`;
    foodName.focus();
    return;
  }
  items.push({ name, type: foodType.value });
  if (saveItems()) status.textContent = `«${name}» добавлен в карточку.`;
  renderItems();
  foodName.value = '';
  foodName.focus();
});

renderItems();
updateAccount();
