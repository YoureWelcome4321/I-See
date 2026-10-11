const code = new URLSearchParams(window.location.search).get("code");
const name = document.querySelector("#product-name");
const meta = document.querySelector("#product-meta");
const status = document.querySelector("#product-status");
const details = document.querySelector("#product-details");
const ingredients = document.querySelector("#product-ingredients");
const allergens = document.querySelector("#product-allergens");
const additives = document.querySelector("#product-additives");
const imageWrap = document.querySelector("#product-image-wrap");
const itemId = new URLSearchParams(window.location.search).get("item");
const saveButton = document.querySelector("#save-check");
const checkStatus = document.querySelector("#check-status");
const loginLink = document.querySelector("#check-login-link");
let checkPayload = null;

function showError(message) {
  name.textContent = "Не удалось показать продукт";
  status.textContent = message;
  status.classList.add("product-status-error");
}

function displayTags(tags = []) {
  return [...new Set(tags)]
    .map((tag) => tag.replace(/^[a-z]{2}:/i, "").replace(/-/g, " "))
    .join(", ");
}

function additiveSummary(product) {
  const tags = [
    ...new Set(
      product.additives_original_tags?.length
        ? product.additives_original_tags
        : product.additives_tags || [],
    ),
  ];
  if (!tags.length) {
    return product.additives_n === 0
      ? "В базе добавки не указаны. Сверьте сведения с упаковкой."
      : "Сведения о добавках в базе не указаны. Сверьте сведения с упаковкой.";
  }
  const entries = tags.map((tag) => {
    const codeMatch = tag.match(/e\d+[a-z]?/i);
    return codeMatch
      ? codeMatch[0].toUpperCase()
      : tag.replace(/^[a-z]{2}:/i, "").replace(/-/g, " ");
  });
  return `Добавки по базе: ${entries.join(", ")}. Не все пищевые добавки являются консервантами.`;
}

async function loadProduct() {
  if (!code && !itemId) {
    showError(
      "Сначала нажмите «Сканировать штрихкод» и наведите камеру на штрихкод продукта.",
    );
    return;
  }
  status.textContent = itemId ? "Загружаем товар с сервера…" : "Ищем товар в базе Open Food Facts…";
  try {
    let product;
    if (itemId) {
      product = await YaVizhuAPI.request(`/api/products/${encodeURIComponent(itemId)}`);
      checkPayload = { product_id: product.id };
    } else {
      const fields = "product_name,product_name_ru,brands,quantity,ingredients_text,ingredients_text_ru,allergens,allergens_tags,additives_n,additives_tags,additives_original_tags,image_front_url,image_front_small_url";
      const response = await fetch(`/api/off/products/${encodeURIComponent(code)}?fields=${fields}`);
      if (!response.ok) throw new Error("network");
      const payload = await response.json();
      if (payload.status !== 1 || !payload.product) {
        name.textContent = "Товар не найден";
        status.textContent = "Этого штрихкода пока нет в базе. Попробуйте отсканировать ещё раз или проверьте цифры на упаковке.";
        return;
      }
      product = payload.product;
      checkPayload = { product: {
        name: product.product_name_ru || product.product_name || "Название не указано",
        barcode: code,
        ingredients: product.ingredients_text_ru || product.ingredients_text || "",
        allergens: product.allergens || displayTags(product.allergens_tags),
      } };
    }
    name.textContent =
      product.product_name_ru || product.product_name || product.name || "Название не указано";
    meta.textContent = [product.brands, product.quantity, product.category]
      .filter(Boolean)
      .join(" · ");
    ingredients.textContent =
      product.ingredients_text_ru ||
      product.ingredients_text ||
      product.ingredients ||
      "Состав не указан в базе. Проверьте упаковку.";
    allergens.textContent =
      product.allergens ||
      displayTags(product.allergens_tags) ||
      "Аллергены не указаны в базе. Это не означает, что их нет в продукте.";
    additives.textContent = additiveSummary(product);
    const photo = product.image_front_small_url || product.image_front_url;
    if (photo) {
      const image = document.createElement("img");
      image.src = photo;
      image.alt = `Упаковка продукта ${name.textContent}`;
      image.className = "product-photo-large";
      imageWrap.append(image);
      imageWrap.hidden = false;
    }
    status.textContent = itemId ? `Товар из каталога · ${product.barcode || 'штрихкод не указан'}.` : `Штрихкод: ${code}. Информация из Open Food Facts.`;
    details.hidden = false;
    saveButton.hidden = false;
  } catch (error) {
    showError(error.message || "Не удалось связаться с базой продуктов. Проверьте интернет и попробуйте снова.");
  }
}

saveButton.addEventListener("click", async () => {
  if (!YaVizhuAPI.hasToken()) {
    loginLink.hidden = false;
    checkStatus.textContent = "Чтобы сохранить проверку, сначала войдите в профиле.";
    return;
  }
  saveButton.disabled = true;
  checkStatus.textContent = "Сохраняем результат на сервере…";
  try {
    const record = await YaVizhuAPI.request('/api/checks', { method: 'POST', body: JSON.stringify(checkPayload) });
    const message = record.result === 'warning'
      ? `Обнаружено совпадение с карточкой питания: ${record.matches.join(', ')}. Сверьте полный состав на упаковке.`
      : record.result === 'unknown'
        ? record.reason === 'no_restrictions'
          ? 'Проверка сохранена. Добавьте ограничения в медицинскую карточку, чтобы сравнивать состав.'
          : 'Проверка сохранена, но в базе недостаточно данных о составе для сравнения. Сверьте упаковку.'
        : 'Проверка сохранена. Совпадений с вашей карточкой не найдено; всё равно сверяйте упаковку.';
    checkStatus.textContent = message;
  } catch (error) {
    checkStatus.textContent = error.message;
  } finally { saveButton.disabled = false; }
});

loadProduct();
