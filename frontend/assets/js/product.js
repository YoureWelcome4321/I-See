const params = new URLSearchParams(window.location.search);
const barcode = params.get("code");
const catalogItemId = params.get("item");
const nameNode = document.querySelector("#product-name");
const metaNode = document.querySelector("#product-meta");
const statusNode = document.querySelector("#product-status");
const detailsSection = document.querySelector("#product-result-section");
const detailsGrid = document.querySelector("#product-details");
const imageWrap = document.querySelector("#product-image-wrap");
const imagePlaceholder = document.querySelector(".scan-product-placeholder");
const saveButton = document.querySelector("#save-check");
const checkStatus = document.querySelector("#check-status");
const loginLink = document.querySelector("#check-login-link");
const aiSourcesSection = document.querySelector("#ai-sources-section");
const aiSourcesList = document.querySelector("#ai-sources-list");
let checkPayload = null;

function setProductStatus(message, state = "info") {
  statusNode.textContent = message;
  statusNode.dataset.state = state;
}

function tagsToText(tags = []) {
  return [...new Set(tags)]
    .map((tag) => String(tag).replace(/^[a-z]{2}:/i, "").replace(/-/g, " "))
    .join(", ");
}

function getAdditives(product) {
  if (product.ai_enriched_fields?.additives) return product.ai_enriched_fields.additives;
  if (product.additives_info) return product.additives_info;
  const tags = [...new Set(product.additives_original_tags?.length
    ? product.additives_original_tags
    : product.additives_tags || [])];
  if (!tags.length) {
    if (fieldWasNotFound(product, "additives")) return missingFieldText("additives");
    return product.additives_n === 0
      ? "В базе добавки не указаны. Сверьте сведения с упаковкой."
      : "Сведения о добавках в базе отсутствуют. Сверьте упаковку.";
  }
  const labels = tags.map((tag) => String(tag).match(/e\d+[a-z]?/i)?.[0]?.toUpperCase()
    || String(tag).replace(/^[a-z]{2}:/i, "").replace(/-/g, " "));
  return `Добавки по базе: ${labels.join(", ")}. Не все пищевые добавки являются консервантами.`;
}

function getNutrition(product) {
  if (product.ai_enriched_fields?.nutrition) return product.ai_enriched_fields.nutrition;
  if (product.nutrition) return product.nutrition;
  const n = product.nutriments || {};
  const labels = [
    ["energy-kcal_100g", "Энергия", "ккал"], ["proteins_100g", "Белки", "г"],
    ["fat_100g", "Жиры", "г"], ["carbohydrates_100g", "Углеводы", "г"],
    ["sugars_100g", "сахара", "г"], ["salt_100g", "соль", "г"],
  ];
  const values = labels.filter(([key]) => n[key] !== undefined && n[key] !== null && n[key] !== "")
    .map(([key, label, unit]) => `${label}: ${n[key]} ${unit}`);
  return values.length ? `На 100 г/мл: ${values.join("; ")}.` : fieldWasNotFound(product, "nutrition")
    ? missingFieldText("nutrition")
    : "Пищевая ценность не найдена.";
}

function missingFieldLabel(field) {
  return {
    ingredients: "состав",
    allergens: "аллергены",
    additives: "добавки",
    product_info: "информацию о продукте",
    nutrition: "пищевую ценность",
  }[field] || field;
}

function missingFieldText(field) {
  return {
    ingredients: "Состав не найден в доступных источниках. Проверьте упаковку.",
    allergens: "Аллергены не найдены в доступных источниках. Это не означает, что их нет в продукте.",
    additives: "Добавки не найдены в доступных источниках. Сверьте упаковку.",
    product_info: "Дополнительная информация не найдена в доступных источниках.",
    nutrition: "Пищевая ценность не найдена в доступных источниках. Сверьте упаковку.",
  }[field] || "Данные не найдены в доступных источниках.";
}

function fieldWasNotFound(product, field) {
  return Array.isArray(product.ai_missing_fields) && product.ai_missing_fields.includes(field);
}

function showProductError(message) {
  nameNode.textContent = "Не удалось найти продукт";
  metaNode.textContent = barcode ? `Штрихкод · ${barcode}` : "Проверьте подключение и повторите попытку";
  setProductStatus(message, "error");
  detailsSection.hidden = true;
  saveButton.hidden = true;
}

function showProduct(product, source) {
  const name = product.ai_enriched_fields?.product_name || product.product_name_ru || product.product_name || product.name || "Название не указано";
  nameNode.textContent = name;
  const meta = [product.brands, product.quantity, product.category].filter(Boolean);
  metaNode.textContent = meta.join(" · ") || (barcode ? `Штрихкод · ${barcode}` : "Информация о продукте");

  document.querySelector("#product-ingredients").textContent = product.ai_enriched_fields?.ingredients
    || product.ingredients_text_ru || product.ingredients_text || product.ingredients
    || (fieldWasNotFound(product, "ingredients") ? missingFieldText("ingredients") : "Состав не указан в базе. Проверьте упаковку.");
  document.querySelector("#product-allergens").textContent = product.ai_enriched_fields?.allergens
    || product.allergens || tagsToText(product.allergens_tags)
    || (fieldWasNotFound(product, "allergens") ? missingFieldText("allergens") : "Аллергены не указаны в базе. Это не означает, что их нет в продукте.");
  document.querySelector("#product-additives").textContent = getAdditives(product);
  const infoNode = document.querySelector("#product-info");
  const nutritionNode = document.querySelector("#product-nutrition");
  if (infoNode) infoNode.textContent = product.ai_enriched_fields?.product_info
    || product.product_info
    || (fieldWasNotFound(product, "product_info") ? missingFieldText("product_info") : [product.brands, product.product_name_ru || product.product_name, product.quantity].filter(Boolean).join(" · "))
    || "Дополнительная информация не найдена.";
  if (nutritionNode) nutritionNode.textContent = getNutrition(product);

  const photoUrl = product.image_front_small_url || product.image_front_url;
  if (photoUrl) {
    const image = document.createElement("img");
    image.src = photoUrl;
    image.alt = `Упаковка продукта ${name}`;
    image.className = "scan-product-photo-image";
    image.addEventListener("error", () => {
      imageWrap.hidden = true;
      imagePlaceholder.hidden = false;
    }, { once: true });
    imageWrap.replaceChildren(image);
    imageWrap.hidden = false;
    imagePlaceholder.hidden = true;
  } else {
    imageWrap.replaceChildren();
    imageWrap.hidden = true;
    imagePlaceholder.hidden = false;
  }

  detailsSection.hidden = false;
  detailsGrid.hidden = false;
  saveButton.hidden = false;
  setProductStatus(source, "success");
}

async function enrichMissingFields(product) {
  const ingredients = product.ingredients_text_ru || product.ingredients_text || product.ingredients || "";
  const allergens = product.allergens || tagsToText(product.allergens_tags);
  const additivesKnown = Boolean(product.additives_original_tags?.length || product.additives_tags?.length || product.additives_n === 0);
  const nutritionKnown = Boolean(product.nutrition || Object.keys(product.nutriments || {}).length);
  const missing = [
    "product_name",
    ...(!ingredients.trim() ? ["ingredients"] : []),
    ...(!allergens.trim() ? ["allergens"] : []),
    ...(!nutritionKnown ? ["nutrition"] : []),
    ...(!additivesKnown ? ["additives"] : []),
    ...(!(product.product_info || "").trim() ? ["product_info"] : []),
  ];
  if (!missing.length) return { product, usedAi: false, triedAi: false, confirmed: true, missing: [] };

  try {
    const enriched = await YaVizhuAPI.request("/api/ai/product-details", {
      method: "POST",
      body: JSON.stringify({
        name: product.product_name_ru || product.product_name || product.name || "",
        brand: product.brands || "",
        country: "Россия",
        missing,
        known_data: {
          name: product.product_name_ru || product.product_name || product.name || "",
          product_name: product.product_name_ru || product.product_name || product.name || "",
          brand: product.brands || "",
          quantity: product.quantity || "",
          category: product.categories || product.category || "",
          ingredients: ingredients,
          allergens: allergens,
          additives: additivesKnown ? getAdditives(product) : "",
          nutrition: product.nutrition || (Object.keys(product.nutriments || {}).length ? getNutrition(product) : ""),
          product_info: product.product_info || "",
        },
      }),
    });
    // Sources are used by the backend for verification, but the user-facing
    // result is the extracted product information, not a list of web pages.
    const unresolved = Array.isArray(enriched.missing) ? enriched.missing : missing;
    if (!enriched.fields || !Object.keys(enriched.fields).length) {
      return {
        product: { ...product, ai_missing_fields: unresolved },
        usedAi: false,
        triedAi: true,
        confirmed: unresolved.length === 0,
        missing: unresolved,
      };
    }

    const merged = {
      ...product,
      ai_enriched_fields: enriched.fields,
      ai_missing_fields: unresolved,
    };
    // Confirmed AI values take precedence over absent or stale database values,
    // and are copied into the canonical fields used when saving a check.
    if (enriched.fields.ingredients) merged.ingredients_text_ru = enriched.fields.ingredients;
    if (enriched.fields.product_name) merged.product_name_ru = enriched.fields.product_name;
    if (enriched.fields.allergens) merged.allergens = enriched.fields.allergens;
    if (enriched.fields.additives) merged.additives_info = enriched.fields.additives;
    if (enriched.fields.product_info) merged.product_info = enriched.fields.product_info;
    if (enriched.fields.nutrition) merged.nutrition = enriched.fields.nutrition;
    aiSourcesSection.hidden = true;
    return { product: merged, usedAi: true, triedAi: true, confirmed: unresolved.length === 0, missing: unresolved, confidence: enriched.confidence };
  } catch (error) {
    // The original Open Food Facts result remains usable when AI search is unavailable or unconfigured.
    console.info("AI product enrichment skipped:", error.message);
    return { product, usedAi: false, triedAi: true, reason: error.message || "" };
  }
}

async function loadProduct() {
  if (!barcode && !catalogItemId) {
    showProductError("Вернитесь на главную и наведите камеру на штрихкод продукта.");
    return;
  }

  setProductStatus(catalogItemId ? "Загружаем товар из каталога…" : "Ищем продукт в базе…", "loading");
  try {
    if (catalogItemId) {
      const product = await YaVizhuAPI.request(`/api/products/${encodeURIComponent(catalogItemId)}`);
      checkPayload = { product_id: product.id };
      showProduct(product, `Товар из каталога · ${product.barcode || "штрихкод не указан"}`);
      return;
    }

    const fields = [
      "product_name", "product_name_ru", "brands", "quantity", "ingredients_text",
      "ingredients_text_ru", "allergens", "allergens_tags", "additives_n", "additives_tags",
      "additives_original_tags", "nutriments", "categories", "image_front_url", "image_front_small_url",
    ].join(",");
    const response = await fetch(`/api/off/products/${encodeURIComponent(barcode)}?fields=${encodeURIComponent(fields)}`);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || payload.error || "Сервис поиска продукта временно недоступен.");
    if (payload.status !== 1 || !payload.product) {
      showProductError("Такого штрихкода пока нет в базе. Проверьте цифры на упаковке или попробуйте другой продукт.");
      return;
    }

    let product = payload.product;
    const missingIngredients = !(product.ingredients_text_ru || product.ingredients_text || "").trim();
    const missingAllergens = !(product.allergens || tagsToText(product.allergens_tags)).trim();
    let aiSourceLabel = "";
    const needsAiDetails = missingIngredients || missingAllergens
      || !(product.product_info || "").trim()
      || !product.nutrition && !Object.keys(product.nutriments || {}).length
      || !(product.additives_original_tags?.length || product.additives_tags?.length || product.additives_n === 0);
    if (needsAiDetails) {
      setProductStatus("Ищем состав, аллергены, добавки и пищевую ценность по названию продукта…", "loading");
      const result = await enrichMissingFields(product);
      product = result.product;
      if (result.missing?.length) {
        aiSourceLabel = ` · ИИ не нашёл: ${result.missing.map(missingFieldLabel).join(", ")}`;
      } else if (result.usedAi) {
        aiSourceLabel = " · недостающие данные дополнены поиском ИИ";
      }
      else if (result.reason?.includes("AI_NOT_CONFIGURED")) aiSourceLabel = " · поиск ИИ не настроен: задайте OPENROUTER_API_KEY и перезапустите сервер";
      else if (result.reason) aiSourceLabel = ` · поиск ИИ недоступен: ${result.reason}`;
      else if (result.triedAi) aiSourceLabel = " · ИИ не смог подтвердить точное совпадение с источниками";
    }
    checkPayload = { product: {
      name: product.ai_enriched_fields?.product_name || product.product_name_ru || product.product_name || "Название не указано",
      barcode,
      ingredients: product.ingredients_text_ru || product.ingredients_text || "",
      allergens: product.allergens || tagsToText(product.allergens_tags),
    } };
    showProduct(product, `Штрихкод · ${barcode} · Open Food Facts${aiSourceLabel}`);
  } catch (error) {
    showProductError(error.message || "Не удалось связаться с базой продуктов. Попробуйте ещё раз.");
  }
}

saveButton.addEventListener("click", async () => {
  if (!window.YaVizhuAPI?.hasToken()) {
    loginLink.hidden = false;
    checkStatus.textContent = "Войдите в профиль, чтобы сохранить результат проверки.";
    checkStatus.dataset.state = "info";
    return;
  }

  saveButton.disabled = true;
  checkStatus.textContent = "Сохраняем результат…";
  checkStatus.dataset.state = "loading";
  try {
    const record = await YaVizhuAPI.request("/api/checks", {
      method: "POST",
      body: JSON.stringify(checkPayload),
    });
    if (record.result === "warning") {
      checkStatus.textContent = `В составе найдено совпадение с вашей карточкой: ${record.matches.join(", ")}. Сверьте полный состав на упаковке.`;
      checkStatus.dataset.state = "warning";
    } else if (record.result === "unknown") {
      checkStatus.textContent = record.reason === "no_restrictions"
        ? "Проверка сохранена. Добавьте ограничения в профиле, чтобы сравнивать состав продуктов."
        : "Проверка сохранена, но в базе недостаточно сведений для сравнения. Сверьте упаковку.";
      checkStatus.dataset.state = "info";
    } else {
      checkStatus.textContent = "Проверка сохранена. Совпадений с карточкой питания не найдено; всё равно сверьте упаковку.";
      checkStatus.dataset.state = "success";
    }
    loginLink.hidden = true;
  } catch (error) {
    checkStatus.textContent = error.message || "Не получилось сохранить результат. Попробуйте ещё раз.";
    checkStatus.dataset.state = "error";
  } finally {
    saveButton.disabled = false;
  }
});

loadProduct();
