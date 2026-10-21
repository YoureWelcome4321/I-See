if (!localStorage.getItem("ya-vizhu-onboarding-done-v1") && !window.location.pathname.endsWith("onboarding.html")) {
  window.location.replace("onboarding.html");
}

const savedFontSize = localStorage.getItem("ya-vizhu-font-size");
if (savedFontSize) document.documentElement.dataset.fontSize = savedFontSize;

const ADVICE = {
  start: { title: "Как пользоваться сайтом", text: "Нажмите «Начать сканирование» на главной странице и наведите камеру на штрихкод. После проверки вы увидите состав и аллергены. В профиле можно сохранить ограничения, а в разделе «Рецепты» — найти подходящие блюда.", linkText: "Начать сканирование", href: "index.html?scan=1" },
  scan: { title: "Как проверить продукт", text: "Нажмите «Начать сканирование», разрешите доступ к камере и наведите её на полоски штрихкода. Держите телефон ровно. После распознавания откроется страница продукта с составом, аллергенами и добавками.", linkText: "Открыть сканер", href: "index.html?scan=1" },
  general: {
    title: "Начните с выделенных предупреждений",
    text: "Сначала найдите на упаковке состав и раздел «Аллергены». Затем посмотрите срок годности и условия хранения.",
    linkText: "Как читать этикетку",
    href: "help.html",
  },
  allergens: {
    title: "Где искать аллергены",
    text: "Ищите отдельную строку «Аллергены» и выделенные ингредиенты в полном составе. Даже знакомый продукт может изменить рецепт — проверяйте упаковку каждый раз.",
    linkText: "Открыть мою карточку",
    href: "medical-card.html",
  },
  profile: { title: "Как настроить профиль", text: "Откройте «Профиль» и добавьте продукты, которые вызывают аллергию или которые вы не едите. Пишите простыми словами, например «арахис» или «молоко». Эти записи помогут проверять продукты и подбирать рецепты.", linkText: "Открыть профиль", href: "medical-card.html" },
  recipes: { title: "Как найти подходящий рецепт", text: "Откройте «Рецепты для вас». Сайт уберёт блюда с продуктами, которые указаны в вашем профиле. Нажмите на карточку рецепта, чтобы увидеть ингредиенты и пошаговое приготовление.", linkText: "Открыть рецепты", href: "recipes.html" },
  catalog: { title: "Как посмотреть товары", text: "В разделе «Товары для вас» можно найти продукты из каталога. Нажмите на карточку товара, чтобы посмотреть его состав, аллергены и добавки.", linkText: "Открыть каталог", href: "catalog.html" },
  stores: { title: "Как найти магазин рядом", text: "Откройте «Магазины на карте» и разрешите сайту определить ваше местоположение. Вы увидите продуктовые магазины рядом с вами.", linkText: "Открыть карту магазинов", href: "stores.html" },
  composition: {
    title: "Состав читается сверху вниз",
    text: "Ингредиенты перечислены по убыванию количества. Первые несколько позиций помогают понять основу продукта и наличие добавленного сахара или соли.",
    linkText: "Ещё про этикетку",
    href: "help.html",
  },
  additives: {
    title: "Что означают E-коды",
    text: "E-код — это обозначение пищевой добавки, но само по себе оно не говорит, подходит ли продукт именно вам. Смотрите на назначение добавки и учитывайте личные ограничения.",
    linkText: "Записать ограничение",
    href: "medical-card.html",
  },
  card: {
    title: "Соберите свою карточку",
    text: "В медицинской карточке можно сохранить аллергии и продукты, которых вы избегаете. Данные остаются в этом браузере и никуда не отправляются.",
    linkText: "Открыть медицинскую карточку",
    href: "medical-card.html",
  },
  label: {
    title: "Смотрите на четыре вещи",
    text: "Проверьте название, состав, аллергены, срок годности и условия хранения. Если информация стёрта или неполна, лучше выбрать другой продукт.",
    linkText: "Открыть инструкцию",
    href: "help.html",
  },
};

function initAdvice() {
  const dialog = document.querySelector("#advice-dialog");
  const form = document.querySelector("#advice-form");
  const topicSelect = document.querySelector("#advice-topic");
  const result = document.querySelector("#advice-result");
  const triggers = document.querySelectorAll(
    "[data-advice-topic], #open-advice, #open-advice-bottom",
  );

  if (!dialog || !form || !topicSelect || !result || !triggers.length) return;

  let lastTrigger = null;
  let nativeOpen = false;
  let previousOverflow = "";

  function lockPage() {
    previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
  }

  function unlockPage() {
    document.body.style.overflow = previousOverflow;
    previousOverflow = "";
  }

  function restoreFocus() {
    if (lastTrigger?.isConnected) lastTrigger.focus();
    lastTrigger = null;
  }

  function clearAdvice() {
    result.replaceChildren();
    result.removeAttribute("data-ready");
  }

  function openAdvice(topic = "general", trigger) {
    lastTrigger = trigger || document.activeElement;
    topicSelect.value = ADVICE[topic] ? topic : "general";
    clearAdvice();
    lockPage();

    if (typeof dialog.showModal === "function") {
      nativeOpen = true;
      dialog.showModal();
    } else {
      nativeOpen = false;
      dialog.classList.add("is-fallback");
      dialog.setAttribute("aria-modal", "true");
      dialog.setAttribute("open", "");
    }
    topicSelect.focus();
  }

  function closeAdvice() {
    if (nativeOpen && typeof dialog.close === "function") {
      dialog.close();
      return;
    }
    dialog.classList.remove("is-fallback");
    dialog.removeAttribute("open");
    unlockPage();
    restoreFocus();
  }

  function renderAdvice(topic) {
    const advice = ADVICE[topic] || ADVICE.general;
    clearAdvice();
    const heading = document.createElement("h3");
    heading.textContent = advice.title;
    const paragraph = document.createElement("p");
    paragraph.textContent = advice.text;
    const link = document.createElement("a");
    link.className = "advice-result-link";
    link.href = advice.href;
    link.textContent = advice.linkText;
    result.append(heading, paragraph, link);
    result.setAttribute("data-ready", "true");
    result.focus({ preventScroll: true });
  }

  triggers.forEach((trigger) => {
    trigger.addEventListener("click", () => {
      openAdvice(trigger.dataset.adviceTopic || "general", trigger);
    });
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    renderAdvice(topicSelect.value);
  });

  dialog.querySelectorAll("[data-advice-close]").forEach((button) => {
    button.addEventListener("click", closeAdvice);
  });

  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) closeAdvice();
  });

  dialog.addEventListener("close", () => {
    if (!nativeOpen) return;
    nativeOpen = false;
    unlockPage();
    restoreFocus();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && dialog.classList.contains("is-fallback")) {
      event.preventDefault();
      closeAdvice();
    }
  });
}

function initScanner() {
  const startButton = document.querySelector("#start-scan");
  const closeButton = document.querySelector("#close-scan");
  const switchButton = document.querySelector("#switch-camera");
  const torchButton = document.querySelector("#torch-button");
  const torchLabel = document.querySelector("#torch-label");
  const scanner = document.querySelector("#scanner");
  const video = document.querySelector("#camera");
  const cameraFrame = document.querySelector("#camera-frame");
  const cameraMessage = document.querySelector("#camera-message");
  const hint = document.querySelector("#scanner-hint");

  if (
    !startButton ||
    !closeButton ||
    !switchButton ||
    !torchButton ||
    !scanner ||
    !video ||
    !cameraFrame ||
    !cameraMessage ||
    !hint
  ) {
    return;
  }

  let stream = null;
  let reader = null;
  let scanCanvas = null;
  let scanContext = null;
  let scanAngle = 0;
  let detector = null;
  let scanTimer = null;
  let fallbackTimer = null;
  let facingMode = "environment";
  let scanning = false;
  let torchOn = false;

  function setHint(text, isError = false) {
    hint.textContent = text;
    hint.classList.toggle("error", isError);
  }

  async function startCamera() {
    stopCamera();
    cameraMessage.hidden = false;
    cameraMessage.textContent = "Запрашиваем доступ к камере…";
    setHint("Разрешите доступ к камере, когда браузер спросит.");

    if (!navigator.mediaDevices?.getUserMedia) {
      cameraMessage.textContent = "Камера работает только на сайте с HTTPS.";
      setHint("Откройте защищённую версию сайта по HTTPS.", true);
      return;
    }

    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          facingMode: { ideal: facingMode },
          width: { ideal: 1920 },
          height: { ideal: 1080 },
        },
      });
      video.srcObject = stream;
      await video.play();
      cameraMessage.hidden = true;
      cameraFrame.classList.add("is-active");

      const cameras = (await navigator.mediaDevices.enumerateDevices()).filter(
        (item) => item.kind === "videoinput",
      );
      switchButton.hidden = cameras.length < 2;
      const torchSupported = Boolean(stream.getVideoTracks()[0]?.getCapabilities?.().torch);
      torchButton.hidden = false;
      torchButton.disabled = !torchSupported;
      torchButton.title = torchSupported ? "Включить вспышку камеры" : "Вспышка не поддерживается этой камерой";
      torchOn = false;
      torchButton.setAttribute("aria-pressed", "false");
      torchLabel.textContent = torchSupported ? "Включить фонарик" : "Фонарик недоступен";
      setHint("Покажите штрихкод целиком. Сканер ищет его автоматически.");
      startDetection();
    } catch (error) {
      const messages = {
        NotAllowedError: "Доступ к камере запрещён. Разрешите его в настройках браузера.",
        NotFoundError: "Не нашли камеру на этом устройстве.",
        NotReadableError: "Камера занята другим приложением. Закройте его и попробуйте снова.",
      };
      cameraMessage.textContent =
        messages[error.name] || "Не получилось открыть камеру. Закройте окно и попробуйте снова.";
      setHint(cameraMessage.textContent, true);
    }
  }

  function startDetection() {
    scanning = true;
    if ("BarcodeDetector" in window) {
      BarcodeDetector.getSupportedFormats()
        .then((formats) => {
          if (!scanning) return;
          const supported = ["ean_13", "ean_8", "upc_a", "upc_e", "code_128", "itf"].filter(
            (format) => formats.includes(format),
          );
          if (supported.length) {
            detector = new BarcodeDetector({ formats: supported });
            detectWithBrowser();
            fallbackTimer = window.setTimeout(() => {
              if (!scanning || reader) return;
              detector = null;
              window.clearTimeout(scanTimer);
              startZxing();
            }, 5000);
            return;
          }
          startZxing();
        })
        .catch(startZxing);
    } else {
      startZxing();
    }
  }

  function startZxing() {
    if (!scanning || reader || !stream) return;
    if (!window.ZXingBrowser?.BrowserMultiFormatReader) {
      setHint("Не загрузился сканер. Проверьте интернет и обновите страницу.", true);
      return;
    }
    try {
      const hints = new Map([[3, true]]);
      reader = new ZXingBrowser.BrowserMultiFormatReader(hints);
      scanCanvas = document.createElement("canvas");
      scanContext = scanCanvas.getContext("2d", { willReadFrequently: true });
      scanAngle = 0;
      if (!scanContext) throw new Error("Не удалось подготовить изображение камеры.");
      setHint("Камера включена. Наведите штрихкод на экран и держите телефон неподвижно.");
      scanWithZxing();
    } catch (error) {
      reader = null;
      setHint(error.message || "Не получилось запустить распознавание.", true);
    }
  }

  function scanWithZxing() {
    if (!scanning || !reader || !scanContext || !stream) return;
    if (video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA || !video.videoWidth) {
      scanTimer = window.setTimeout(scanWithZxing, 200);
      return;
    }

    const sourceWidth = video.videoWidth;
    const sourceHeight = video.videoHeight;
    const scale = Math.min(1, 1280 / Math.max(sourceWidth, sourceHeight));
    const width = Math.round(sourceWidth * scale);
    const height = Math.round(sourceHeight * scale);
    const angle = scanAngle;
    scanAngle = (scanAngle + 90) % 360;
    scanCanvas.width = angle % 180 === 0 ? width : height;
    scanCanvas.height = angle % 180 === 0 ? height : width;
    scanContext.setTransform(1, 0, 0, 1, 0, 0);
    scanContext.clearRect(0, 0, scanCanvas.width, scanCanvas.height);
    scanContext.translate(scanCanvas.width / 2, scanCanvas.height / 2);
    scanContext.rotate((angle * Math.PI) / 180);
    scanContext.drawImage(video, -width / 2, -height / 2, width, height);

    try {
      const result = reader.decodeFromCanvas(scanCanvas);
      if (result) {
        onBarcode(result.getText());
        return;
      }
    } catch {
      // This frame or orientation did not contain a readable barcode.
    }
    scanTimer = window.setTimeout(scanWithZxing, 100);
  }

  async function detectWithBrowser() {
    if (!scanning || !detector) return;
    if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
      try {
        const results = await detector.detect(video);
        if (results.length) {
          onBarcode(results[0].rawValue);
          return;
        }
      } catch {
        // A blurry frame can be skipped safely.
      }
    }
    scanTimer = window.setTimeout(detectWithBrowser, 120);
  }

  function onBarcode(code) {
    if (!scanning) return;
    scanning = false;
    stopCamera();
      window.location.href = `product.html?code=${encodeURIComponent(code)}`;
  }

  function stopCamera() {
    scanning = false;
    window.clearTimeout(scanTimer);
    window.clearTimeout(fallbackTimer);
    reader = null;
    scanCanvas = null;
    scanContext = null;
    detector = null;
    if (stream) stream.getTracks().forEach((track) => track.stop());
    stream = null;
    video.srcObject = null;
    cameraFrame.classList.remove("is-active");
    switchButton.hidden = true;
    torchButton.hidden = true;
    torchButton.disabled = false;
    torchOn = false;
  }

  async function toggleTorch() {
    const track = stream?.getVideoTracks()[0];
    if (!track || !track.getCapabilities?.().torch) return;
    try {
      torchOn = !torchOn;
      await track.applyConstraints({ advanced: [{ torch: torchOn }] });
      torchButton.setAttribute("aria-pressed", String(torchOn));
      torchLabel.textContent = torchOn ? "Выключить фонарик" : "Включить фонарик";
    } catch {
      setHint("Фонарик не поддерживается этой камерой.", true);
    }
  }

  function openScanner() {
    scanner.classList.add("is-open");
    scanner.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
    closeButton.focus();
    startCamera();
  }

  function closeScanner() {
    stopCamera();
    scanner.classList.remove("is-open");
    scanner.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
    startButton.focus();
  }

  startButton.addEventListener("click", openScanner);
  closeButton.addEventListener("click", closeScanner);
  torchButton.addEventListener("click", toggleTorch);
  switchButton.addEventListener("click", () => {
    facingMode = facingMode === "environment" ? "user" : "environment";
    startCamera();
  });
  scanner.addEventListener("click", (event) => {
    if (event.target === scanner) closeScanner();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && scanner.classList.contains("is-open")) closeScanner();
  });

  if (new URLSearchParams(window.location.search).has("scan")) {
    openScanner();
  }
}

const STORY_KINDS = { article: "Статья", recipe: "Рецепт", guide: "Инструкция" };

function storyContent(story) {
  const nodes = [];
  const el = (tag, text, className) => { const node = document.createElement(tag); if (text) node.textContent = text; if (className) node.className = className; return node; };
  const list = (items, className) => { const node = el(className === "sv-steps" ? "ol" : "ul", "", className); items.forEach((item) => node.append(el("li", item))); return node; };
  if (story.kind === "recipe" && story.recipe) {
    if (story.recipe.description) nodes.push(el("p", story.recipe.description));
    if (story.recipe.ingredients.length) nodes.push(el("h3", "Что понадобится"), list(story.recipe.ingredients, "sv-ingredients"));
    if (story.recipe.steps.length) nodes.push(el("h3", "Как готовить"), list(story.recipe.steps, "sv-steps"));
    const open = el("a", "", "ui-btn ui-btn--ghost ui-btn--block");
    open.href = `/recipe.html?id=${encodeURIComponent(story.recipe.id)}`;
    open.append(el("span", "Открыть рецепт целиком"));
    nodes.push(open);
  } else if (story.kind === "guide" && story.body) {
    nodes.push(list(story.body.split("\n").map((line) => line.trim()).filter(Boolean), "sv-steps"));
  } else if (story.body) {
    story.body.split(/\n\s*\n/).map((part) => part.trim()).filter(Boolean).forEach((part) => nodes.push(el("p", part)));
  }
  if (!nodes.length) nodes.push(el("p", "Скоро здесь появится рассказ. Загляните чуть позже.", "sv-empty"));
  return nodes;
}

function initStoryViewer(stories) {
  const viewer = document.getElementById("story-viewer");
  if (!viewer) return () => {};
  const $ = (id) => document.getElementById(id);
  let current = 0;
  let opener = null;

  function show(index) {
    current = index;
    const story = stories[index];
    $("sv-image").src = `/assets/images/${story.image}`;
    $("sv-kind").textContent = STORY_KINDS[story.kind] || STORY_KINDS.article;
    $("sv-title").textContent = story.title;
    $("sv-subtitle").textContent = story.subtitle || "";
    $("sv-bars").replaceChildren(...stories.map((_, i) => { const bar = document.createElement("i"); if (i <= index) bar.className = "is-seen"; return bar; }));
    $("sv-body").replaceChildren(...storyContent(story));
    $("sv-body").scrollTop = 0;
    $("sv-prev").hidden = index === 0;
    $("sv-next").querySelector("span").textContent = index === stories.length - 1 ? "Закрыть" : "Дальше";
  }

  function close() { if (viewer.open) viewer.close(); }
  $("sv-close").addEventListener("click", close);
  $("sv-prev").addEventListener("click", () => { if (current > 0) show(current - 1); });
  $("sv-next").addEventListener("click", () => { if (current < stories.length - 1) show(current + 1); else close(); });
  viewer.addEventListener("click", (event) => { if (event.target === viewer) close(); });
  viewer.addEventListener("keydown", (event) => {
    if (event.key === "ArrowRight" && current < stories.length - 1) show(current + 1);
    if (event.key === "ArrowLeft" && current > 0) show(current - 1);
  });
  // Focus returns to the story the person opened, so the keyboard does not lose its place.
  viewer.addEventListener("close", () => { document.body.style.overflow = ""; opener?.focus(); });

  return (index, button) => {
    opener = button;
    show(index);
    document.body.style.overflow = "hidden";
    viewer.showModal();
    $("sv-next").focus();
  };
}

async function initStories() {
  const container = document.querySelector('.quick-links');
  if (!container || !window.YaVizhuAPI) return;
  try {
    const stories = await YaVizhuAPI.request('/api/stories');
    const open = initStoryViewer(stories);
    const buttons = stories.map((story, index) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'recipe-story';
      button.dataset.storyId = story.id;
      button.setAttribute('aria-label', `${STORY_KINDS[story.kind] || STORY_KINDS.article}: ${story.title}`);
      button.addEventListener('click', () => open(index, button));

      const imageWrap = document.createElement('span');
      imageWrap.className = 'story-image';
      const image = document.createElement('img');
      image.src = `/assets/images/${story.image}`;
      image.alt = '';
      if (index === 0) image.fetchPriority = 'high';
      else image.loading = 'lazy';
      imageWrap.append(image);

      const caption = document.createElement('span');
      caption.className = 'story-caption';
      const title = document.createElement('b');
      title.textContent = story.title;
      const subtitle = document.createElement('small');
      subtitle.textContent = story.subtitle || '';
      caption.append(title, subtitle);
      button.append(imageWrap, caption);
      return button;
    });
    container.replaceChildren(...buttons);
  } catch {
    // Без историй главная страница работает как обычно.
  }
}

document.addEventListener("DOMContentLoaded", () => {
  initAdvice();
  initScanner();
  initStories();
});
