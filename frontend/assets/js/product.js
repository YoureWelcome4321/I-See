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

// Open Food Facts stores allergens as English taxonomy tags («en:milk»).
const ALLERGEN_NAMES = {
  milk: "молоко", gluten: "глютен", eggs: "яйца", nuts: "орехи", peanuts: "арахис",
  soybeans: "соя", fish: "рыба", crustaceans: "ракообразные", molluscs: "моллюски",
  "sesame-seeds": "кунжут", mustard: "горчица", celery: "сельдерей", lupin: "люпин",
  "sulphur-dioxide-and-sulphites": "сульфиты",
};

function tagsToText(tags = []) {
  return [...new Set(tags)]
    .map((tag) => {
      const name = String(tag).trim().replace(/^[a-z]{2}:/i, "");
      return ALLERGEN_NAMES[name.toLowerCase()] || name.replace(/-/g, " ");
    })
    .filter(Boolean)
    .join(", ");
}

function allergensText(product) {
  const text = String(product.allergens || "");
  // A tag list («en:milk,en:soybeans») is translated; a sentence from the label or AI is kept as is.
  if (text && text.split(",").every((part) => /^\s*[a-z]{2}:/i.test(part))) return tagsToText(text.split(","));
  return text || tagsToText(product.allergens_tags);
}

function additiveTags(product) {
  return [...new Set(product.additives_original_tags?.length
    ? product.additives_original_tags
    : product.additives_tags || [])];
}

function getAdditives(product) {
  if (product.ai_enriched_fields?.additives) return product.ai_enriched_fields.additives;
  if (product.additives_info) return product.additives_info;
  const tags = additiveTags(product);
  // No additives known: the card is hidden instead of showing an empty placeholder.
  if (!tags.length) return "";
  const labels = tags.map((tag) => {
    const found = window.lookupAdditive?.(tag);
    if (!found) return String(tag).replace(/^[a-z]{2}:/i, "").replace(/-/g, " ");
    return found.entry ? `${found.code} (${found.entry[0].toLowerCase()})` : found.code;
  });
  return `Добавки по базе: ${labels.join(", ")}.`;
}

// E-codes come from Open Food Facts tags or are picked out of a text found by AI («E330, Е 471»).
function additiveItems(product, text) {
  const sources = additiveTags(product).length ? additiveTags(product) : String(text).match(/(?<![A-Za-zА-Яа-яЁё])[EЕ]\s?-?\d{3,4}[a-zA-Z]?/g) || [];
  const items = new Map();
  for (const source of sources) {
    const found = window.lookupAdditive?.(source);
    if (found && !items.has(found.code)) items.set(found.code, found);
  }
  return [...items.values()];
}

const E_CODE = /(?<![A-Za-zА-Яа-яЁё])[EЕ]\s?-?\d{3,4}[a-zA-Z]?(?![A-Za-zА-Яа-яЁё])/g;
// A segment left with only the additive's role («эмульгатор», «регулятор кислотности:») is dropped too.
const ADDITIVE_ROLE = /^(регуляторы? кислотности|эмульгаторы?|консерванты?|красител[ьи]|стабилизаторы?|загустител[ьи]|антиокислител[ьи]|антиоксиданты?|разрыхлител[ьи]( теста)?|усилител[ьи] вкуса( и аромата)?|подсластител[ьи]|глазировател[ьи]|влагоудерживающ(ий|ие) агенты?|фиксаторы? (окраски|цвета)|улучшител[ьи]( муки)?|пеногасител[ьи]|пищев(ая|ые) добавк[аи])?[\s:.;]*$/i;

function stripAdditiveCodes(text) {
  if (!E_CODE.test(text)) return text;
  E_CODE.lastIndex = 0;
  const parts = String(text).split(/,(?![^()]*\))/).map((part) => part
    .replace(E_CODE, "")
    .replace(/\(\s*[,;\s]*\)/g, "")
    .replace(/\(\s*[,;]\s*/g, "(")
    .replace(/\s*[,;]\s*\)/g, ")")
    .replace(/\s{2,}/g, " ")
    .replace(/\s+([,.;:)])/g, "$1")
    .trim());
  const kept = parts.filter((part) => !ADDITIVE_ROLE.test(part));
  const result = kept.join(", ").trim();
  return result && !/[.!]$/.test(result) && /[.!]$/.test(String(text).trim()) ? `${result}.` : result;
}

function renderAdditives(product) {
  const text = getAdditives(product);
  const node = document.querySelector("#product-additives");
  const list = document.querySelector("#product-additives-list");
  const items = additiveItems(product, text);
  node.closest(".scan-detail-card").hidden = !text && !items.length;
  if (!items.length) {
    node.textContent = text;
    list.hidden = true;
    return items;
  }
  node.textContent = `Найдено добавок: ${items.length}. Не все добавки вредны — ниже объяснение каждой.`;
  list.replaceChildren(...items.map(({ code, entry }) => {
    const item = document.createElement("li");
    const title = document.createElement("b");
    title.textContent = entry ? `${code} — ${entry[0]}` : code;
    item.append(title);
    if (entry) {
      const kind = document.createElement("span");
      kind.className = "additive-kind";
      kind.textContent = entry[1];
      const note = document.createElement("span");
      note.className = "additive-note";
      note.textContent = entry[2];
      item.append(kind, note);
    } else {
      item.append(" — этой добавки пока нет в нашем справочнике.");
    }
    return item;
  }));
  list.hidden = false;
  return items;
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
  if (saveButton) saveButton.hidden = true;
}

function showProduct(product, source) {
  const name = product.ai_enriched_fields?.product_name || product.product_name_ru || product.product_name || product.name || "Название не указано";
  nameNode.textContent = name;
  const meta = [product.brands, product.quantity, product.category].filter(Boolean);
  metaNode.textContent = meta.join(" · ");
  metaNode.hidden = !metaNode.textContent;

  const ingredients = stripAdditiveCodes(product.ai_enriched_fields?.ingredients
    || product.ingredients_text_ru || product.ingredients_text || product.ingredients || "");
  document.querySelector("#product-ingredients").textContent = ingredients
    || (fieldWasNotFound(product, "ingredients") ? missingFieldText("ingredients") : "Состав не указан в базе. Проверьте упаковку.");
  const allergens = product.ai_enriched_fields?.allergens || allergensText(product);
  document.querySelector("#product-allergens").textContent = allergens
    || (fieldWasNotFound(product, "allergens") ? missingFieldText("allergens") : "Аллергены не указаны в базе. Это не означает, что их нет в продукте.");
  const additives = renderAdditives(product);
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
  if (saveButton) saveButton.hidden = false;
  setProductStatus("Состав и аллергены показаны ниже.", "success");

  speechSections = buildSpeech(product, { name, ingredients, allergens, additives });
  showSpeechButtons();
}

// ---------- Озвучка страницы для тех, кому трудно читать мелкий текст ----------
const speech = "speechSynthesis" in window ? window.speechSynthesis : null;
const speakAllButton = document.querySelector("#speak-all");
const player = new Audio();
const audioCache = new Map();
// Silent sound played inside the click: Safari then allows starting the real audio after fetch.
const SILENT_WAV = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=";
let speechSections = null;
let speakingButton = null;

const lowerFirst = (value) => String(value).trim().replace(/^./, (letter) => letter.toLowerCase());
const plural = (count, one, few, many) => {
  const n10 = Math.abs(count) % 10, n100 = Math.abs(count) % 100;
  if (n10 === 1 && n100 !== 11) return one;
  if (n10 >= 2 && n10 <= 4 && (n100 < 12 || n100 > 14)) return few;
  return many;
};
const grams = (value) => {
  const rounded = Math.round(Number(value) * 10) / 10;
  const word = Number.isInteger(rounded) ? plural(rounded, "грамм", "грамма", "граммов") : "грамма";
  return `${String(rounded).replace(".", ",")} ${word}`;
};
const ADDITIVE_COUNT = ["", "одна", "две", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять", "десять"];

function spokenNutrition(product) {
  const n = product.nutriments || {};
  const has = (key) => n[key] !== undefined && n[key] !== null && n[key] !== "";
  if (!["energy-kcal_100g", "proteins_100g", "fat_100g", "carbohydrates_100g"].some(has)) {
    const text = document.querySelector("#product-nutrition")?.textContent.trim();
    return text ? `Пищевая ценность. ${text}` : "";
  }
  const per = /(^|[^а-яa-z])(мл|ml|л|l)([^а-яa-z]|$)/i.test(product.quantity || "") ? "В ста миллилитрах" : "В ста граммах";
  const parts = [];
  if (has("energy-kcal_100g")) {
    const kcal = Math.round(Number(n["energy-kcal_100g"]));
    parts.push(`${kcal} ${plural(kcal, "килокалория", "килокалории", "килокалорий")}`);
  }
  const macros = [["proteins_100g", "белков"], ["fat_100g", "жиров"], ["carbohydrates_100g", "углеводов"]]
    .filter(([key]) => has(key)).map(([key, label]) => `${label} ${grams(n[key])}`);
  if (has("sugars_100g") && has("carbohydrates_100g")) macros.push(`из них сахара ${grams(n.sugars_100g)}`);
  if (macros.length) parts.push(macros.join(", "));
  if (has("salt_100g")) parts.push(`соли ${grams(n.salt_100g)}`);
  return `${per}: ${parts.join("; ")}.`;
}

// The page is read as a person would say it, not as a list of headings.
function buildSpeech(product, { name, ingredients, allergens, additives }) {
  const count = additives.length;
  const additivesText = count
    ? [`${count <= 10 ? ADDITIVE_COUNT[count][0].toUpperCase() + ADDITIVE_COUNT[count].slice(1) : count} ${plural(count, "пищевая добавка", "пищевые добавки", "пищевых добавок")}.`,
      ...additives.map(({ code, entry }) => entry
        ? `${code} — это ${lowerFirst(entry[0])}, ${entry[1]}. ${entry[2]}`
        : `${code} — про эту добавку у нас пока нет сведений.`)].join(" ")
    : "";
  return {
    name: `Это ${name}.`,
    allergens: allergens
      ? `Внимание, аллергены: ${lowerFirst(allergens).replace(/\.?$/, ".")}`
      : "Аллергенов в базе не нашлось. Это не значит, что их точно нет, поэтому загляните на упаковку.",
    ingredients: ingredients
      ? `В составе: ${lowerFirst(ingredients).replace(/\.?$/, ".")}`
      : "Состав в базе не нашёлся. Посмотрите его на упаковке.",
    additives: additivesText,
    nutrition: spokenNutrition(product),
  };
}

// Synthesizers read «E330», «г» and «%» badly, so the text is spelled out first.
function toSpeech(value) {
  return String(value)
    .replace(/(?<![A-Za-zА-Яа-яЁё])[EЕ]\s?-?(\d{3,4})([a-zA-Z]?)/g, (_, digits, letter) => ` Е ${digits}${letter ? ` ${letter.toLowerCase()}` : ""} `)
    .replace(/(\d)\.(\d)/g, "$1,$2")
    .replace(/г\/мл/g, "грамм или миллилитров")
    .replace(/колер (IV|III|II|I)(?![A-Za-z])/g, (_, roman) => `колер ${{ I: 1, II: 2, III: 3, IV: 4 }[roman]}`)
    .replace(/(\d)\s*ккал(?![а-яё])/gi, "$1 килокалорий")
    .replace(/(\d)\s*кг(?![а-яё])/gi, "$1 килограмм")
    .replace(/(\d)\s*мл(?![а-яё])/gi, "$1 миллилитров")
    .replace(/(\d)\s*г(?![а-яё])/gi, "$1 грамм")
    .replace(/%/g, " процентов")
    .replace(/[·•|]/g, ", ")
    .replace(/[_*#]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function fullSpeech() {
  const { name, allergens, ingredients, additives, nutrition } = speechSections;
  // Allergens go first: for a shopper it is the most important part.
  return [name, allergens, ingredients, additives, nutrition, "Перед покупкой всё же сверьте состав на упаковке."];
}

function setSpeakingButton(button, state = "playing") {
  if (speakingButton && speakingButton !== button) {
    speakingButton.setAttribute("aria-pressed", "false");
    speakingButton.removeAttribute("aria-busy");
  }
  speakingButton = button;
  speakAllButton.querySelector("span").textContent = button !== speakAllButton ? "Послушать о продукте"
    : state === "loading" ? "Готовим озвучку…" : "Остановить чтение";
  if (!button) return;
  button.setAttribute("aria-pressed", "true");
  if (state === "loading") button.setAttribute("aria-busy", "true"); else button.removeAttribute("aria-busy");
}

function stopSpeaking() {
  player.pause();
  speech?.cancel();
  if (speakingButton) speakingButton.setAttribute("aria-pressed", "false");
  if (speakingButton) speakingButton.removeAttribute("aria-busy");
  setSpeakingButton(null);
}

function fetchSpeech(text) {
  if (!audioCache.has(text)) {
    const request = fetch("/api/tts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) })
      .then((response) => {
        if (!response.ok) throw new Error(`TTS HTTP ${response.status}`);
        return response.blob();
      })
      .then((blob) => URL.createObjectURL(blob));
    // A failed request is forgotten so the next click can try again.
    request.catch(() => audioCache.delete(text));
    audioCache.set(text, request);
  }
  return audioCache.get(text);
}

// Fallback when the server voice is unavailable: the browser's own synthesizer, sentence by sentence
// (Chrome cuts long utterances off after ~15 s).
function browserSpeak(text, button) {
  if (!speech) { stopSpeaking(); return; }
  const chunks = text.match(/[^.!?;]+[.!?;]*/g)?.map((chunk) => chunk.trim()).filter(Boolean) || [];
  const voices = speech.getVoices().filter((voice) => /^ru/i.test(voice.lang));
  const voice = voices.find((item) => /milena|natural|google|yandex|irina|svetlana/i.test(item.name)) || voices[0];
  setSpeakingButton(button);
  chunks.forEach((chunk, index) => {
    const utterance = new SpeechSynthesisUtterance(chunk);
    utterance.lang = "ru-RU";
    if (voice) utterance.voice = voice;
    utterance.rate = 0.9;
    if (index === chunks.length - 1) utterance.onend = () => { if (speakingButton === button) stopSpeaking(); };
    speech.speak(utterance);
  });
}

async function speak(texts, button) {
  if (speakingButton === button) { stopSpeaking(); return; }
  stopSpeaking();
  const text = toSpeech(texts.filter(Boolean).join(" "));
  if (!text) return;
  setSpeakingButton(button, "loading");
  player.src = SILENT_WAV;
  player.play().catch(() => {});
  try {
    const url = await fetchSpeech(text);
    if (speakingButton !== button) return;
    player.src = url;
    player.onended = () => { if (speakingButton === button) stopSpeaking(); };
    setSpeakingButton(button);
    await player.play();
  } catch (error) {
    if (speakingButton !== button) return;
    console.info("Server voice unavailable, using the browser voice:", error.message);
    player.pause();
    browserSpeak(text, button);
  }
}

function showSpeechButtons() {
  if (!speechSections) return;
  speakAllButton.hidden = false;
  document.querySelectorAll(".speak-card").forEach((button) => {
    button.hidden = !speechSections[button.dataset.speak] || button.closest(".scan-detail-card").hidden;
  });
  // The whole-page audio is prepared in advance so the big button starts at once.
  fetchSpeech(toSpeech(fullSpeech().join(" "))).catch(() => {});
}

speakAllButton.addEventListener("click", () => speak(fullSpeech(), speakAllButton));
document.querySelectorAll(".speak-card").forEach((button) => {
  button.addEventListener("click", () => speak([speechSections[button.dataset.speak]], button));
});
window.addEventListener("pagehide", stopSpeaking);

async function enrichMissingFields(product) {
  const ingredients = product.ingredients_text_ru || product.ingredients_text || product.ingredients || "";
  const allergens = allergensText(product);
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
        // The barcode lets the server confirm that a found page is about this exact product.
        barcode: barcode || product.code || "",
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
    const missingAllergens = !(allergensText(product)).trim();
    const needsAiDetails = missingIngredients || missingAllergens
      || !(product.product_info || "").trim()
      || !product.nutrition && !Object.keys(product.nutriments || {}).length
      || !(product.additives_original_tags?.length || product.additives_tags?.length || product.additives_n === 0);
    if (needsAiDetails) {
      setProductStatus("Ищем состав, аллергены, добавки и пищевую ценность по названию продукта…", "loading");
      const result = await enrichMissingFields(product);
      product = result.product;
      // AI/provider diagnostics are intentionally kept out of the customer UI.
    }
    checkPayload = { product: {
      name: product.ai_enriched_fields?.product_name || product.product_name_ru || product.product_name || "Название не указано",
      barcode,
      ingredients: product.ingredients_text_ru || product.ingredients_text || "",
      allergens: allergensText(product),
    } };
    showProduct(product, "");
  } catch (error) {
    showProductError(error.message || "Не удалось связаться с базой продуктов. Попробуйте ещё раз.");
  }
}

if (saveButton) saveButton.addEventListener("click", async () => {
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
