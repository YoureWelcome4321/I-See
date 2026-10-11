const ADVICE = {
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

async function initStories() {
  const container = document.querySelector('.quick-links');
  if (!container || !window.YaVizhuAPI) return;
  try {
    const stories = await YaVizhuAPI.request('/api/stories');
    const links = stories.map((story, index) => {
      const link = document.createElement('a');
      link.className = 'recipe-story';
      link.dataset.storyId = story.id;
      link.href = story.href;

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
      link.append(imageWrap, caption);
      return link;
    });
    container.replaceChildren(...links);
  } catch {
    // Оставляем встроенные истории на случай, если API временно недоступно.
  }
}

document.addEventListener("DOMContentLoaded", () => {
  initAdvice();
  initScanner();
  initStories();
});
