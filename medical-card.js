const storageKey = 'ya-vizhu-medical-card-v1';
const form = document.querySelector('#medical-form');
const foodName = document.querySelector('#food-name');
const foodType = document.querySelector('#food-type');
const list = document.querySelector('#medical-list');
const status = document.querySelector('#medical-status');

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
    return true;
  } catch {
    status.textContent = 'Не удалось сохранить список на этом устройстве.';
    return false;
  }
}

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
