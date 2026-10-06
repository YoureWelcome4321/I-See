const startButton = document.querySelector('#start-scan');
const closeButton = document.querySelector('#close-scan');
const switchButton = document.querySelector('#switch-camera');
const torchButton = document.querySelector('#torch-button');
const scanner = document.querySelector('#scanner');
const video = document.querySelector('#camera');
const cameraFrame = document.querySelector('#camera-frame');
const cameraMessage = document.querySelector('#camera-message');
const hint = document.querySelector('#scanner-hint');
const scanView = document.querySelector('#scan-view');
const productView = document.querySelector('#product-view');
const productContent = document.querySelector('#product-content');
const scanAgainButton = document.querySelector('#scan-again');
const closeProductButton = document.querySelector('#close-product');

let stream = null;
let detector = null;
let scanTimer = null;
let fallbackTimer = null;
let zxingReader = null;
let rotationCanvas = null;
let rotationContext = null;
let rotationIndex = 0;
let facingMode = 'environment';
let scanning = false;
let torchOn = false;

function setMessage(message, state = '') {
  cameraMessage.textContent = message;
  hint.textContent = message;
  hint.className = `scanner-hint ${state}`.trim();
}

async function startCamera() {
  stopCamera();
  setMessage('Запрашиваем доступ к камере…');
  if (!navigator.mediaDevices?.getUserMedia) {
    setMessage('Камера недоступна. Откройте сайт по HTTPS или через localhost.', 'error');
    return;
  }

  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: {
        facingMode: { ideal: facingMode },
        width: { ideal: 1920 },
        height: { ideal: 1080 },
        focusMode: { ideal: 'continuous' },
      },
    });
    video.srcObject = stream;
    await video.play();
    cameraFrame.classList.add('is-active');
    cameraMessage.hidden = true;
    const cameras = (await navigator.mediaDevices.enumerateDevices()).filter((device) => device.kind === 'videoinput');
    switchButton.hidden = cameras.length < 2;
    const capabilities = stream.getVideoTracks()[0]?.getCapabilities?.();
    torchButton.hidden = !capabilities?.torch;
    torchOn = false;
    torchButton.setAttribute('aria-pressed', 'false');
    torchButton.textContent = 'Включить фонарик';
    setMessage('Покажите бутылку целиком и поверните штрихкод к камере. Ищем по всему кадру…');
    beginDetection();
  } catch (error) {
    const messages = {
      NotAllowedError: 'Нет доступа к камере. Разрешите его в настройках браузера и попробуйте снова.',
      NotFoundError: 'Камера не найдена. Подключите камеру и попробуйте ещё раз.',
      NotReadableError: 'Камера уже используется другим приложением. Закройте его и попробуйте снова.',
    };
    setMessage(messages[error.name] || 'Не удалось открыть камеру. Проверьте разрешения браузера и попробуйте снова.', 'error');
    cameraFrame.classList.remove('is-active');
  }
}

function beginDetection() {
  if ('BarcodeDetector' in window) {
    scanning = true;
    // Native detector scans each frame in multiple orientations where supported.
    BarcodeDetector.getSupportedFormats().then((formats) => {
      const preferred = ['ean_13', 'ean_8', 'upc_a', 'upc_e', 'code_128', 'itf'];
      const supported = preferred.filter((format) => formats.includes(format));
      if (!supported.length) throw new Error('No linear barcode formats');
      detector = new BarcodeDetector({ formats: supported });
      detectBarcode();
      // Some native implementations miss small/far codes; retry the same full frame with ZXing.
      fallbackTimer = window.setTimeout(() => {
        if (!scanning) return;
        scanning = false;
        window.clearTimeout(scanTimer);
        detector = null;
        beginZxing();
      }, 2500);
    }).catch(beginZxing);
  } else {
    beginZxing();
  }
}

function beginZxing() {
  if (!scanning && !stream) return;
  if (!window.ZXingBrowser?.BrowserMultiFormatReader) {
    setMessage('Не загрузился сканер. Проверьте интернет и обновите страницу.', 'error');
    return;
  }
  scanning = true;
  // TRY_HARDER plus explicit 0/90/180/270-degree frame rotations handles
  // vertical and upside-down EAN/UPC codes, which reader defaults may miss.
  const hints = new Map();
  hints.set(3, true); // DecodeHintType.TRY_HARDER
  zxingReader = new ZXingBrowser.BrowserMultiFormatReader(hints);
  rotationCanvas = document.createElement('canvas');
  rotationContext = rotationCanvas.getContext('2d', { willReadFrequently: true });
  rotationIndex = 0;
  scanRotatedFrames();
}

function scanRotatedFrames() {
  if (!scanning || !zxingReader || !rotationContext || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) {
    if (scanning) scanTimer = window.setTimeout(scanRotatedFrames, 250);
    return;
  }

  const width = video.videoWidth;
  const height = video.videoHeight;
  if (!width || !height) {
    scanTimer = window.setTimeout(scanRotatedFrames, 200);
    return;
  }

  const angle = rotationIndex * 90;
  rotationIndex = (rotationIndex + 1) % 4;
  rotationCanvas.width = angle % 180 === 0 ? width : height;
  rotationCanvas.height = angle % 180 === 0 ? height : width;
  rotationContext.setTransform(1, 0, 0, 1, 0, 0);
  rotationContext.clearRect(0, 0, rotationCanvas.width, rotationCanvas.height);
  rotationContext.translate(rotationCanvas.width / 2, rotationCanvas.height / 2);
  rotationContext.rotate((angle * Math.PI) / 180);
  rotationContext.drawImage(video, -width / 2, -height / 2, width, height);

  try {
    const result = zxingReader.decodeFromCanvas(rotationCanvas);
    if (result) {
      scanning = false;
      window.clearTimeout(fallbackTimer);
      showProduct(result.getText());
      return;
    }
  } catch { /* This orientation had no readable barcode; try the next one. */ }

  scanTimer = window.setTimeout(scanRotatedFrames, 80);
}

async function detectBarcode() {
  if (!scanning || !detector || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) {
    if (scanning) scanTimer = window.setTimeout(detectBarcode, 250);
    return;
  }
  try {
    const codes = await detector.detect(video);
    if (codes.length > 0) {
      scanning = false;
      window.clearTimeout(fallbackTimer);
      showProduct(codes[0].rawValue);
      return;
    }
  } catch { /* Wait for the next frame. */ }
  scanTimer = window.setTimeout(detectBarcode, 160);
}

async function showProduct(code) {
  stopCamera();
  scanView.hidden = true;
  productView.hidden = false;
  productContent.replaceChildren();
  closeProductButton.focus();
  const loading = document.createElement('p');
  loading.className = 'product-loading';
  loading.textContent = `Штрихкод считан: ${code}. Загружаем информацию о продукте…`;
  productContent.append(loading);
  try {
    const fields = 'product_name,product_name_ru,brands,quantity,ingredients_text,ingredients_text_ru,allergens,allergens_tags,allergens_hierarchy,additives_n,additives_tags,additives_original_tags,ingredients,nutriscore_grade,nutriments,image_front_url,image_front_small_url,code';
    const response = await fetch(`https://world.openfoodfacts.org/api/v2/product/${encodeURIComponent(code)}.json?fields=${fields}`);
    if (!response.ok) throw new Error('Product lookup failed');
    const data = await response.json();
    if (data.status !== 1 || !data.product) {
      renderNotFound(code);
      return;
    }
    renderProduct(code, data.product);
  } catch {
    renderLookupError(code);
  }
}

function renderProduct(code, product) {
  const name = product.product_name_ru || product.product_name || 'Название не указано';
  const details = [product.brands, product.quantity].filter(Boolean).join(' · ');
  const ingredients = product.ingredients_text_ru || product.ingredients_text;
  const photoUrl = product.image_front_small_url || product.image_front_url;
  const result = document.createElement('section');
  result.className = 'product-result';
  result.setAttribute('aria-live', 'polite');
  const title = document.createElement('h3');
  title.textContent = name;
  result.append(title);
  if (details) {
    const line = document.createElement('p');
    line.className = 'product-details';
    line.textContent = details;
    result.append(line);
  }
  if (photoUrl) {
    const photo = document.createElement('img');
    photo.className = 'product-photo';
    photo.src = photoUrl;
    photo.alt = `Упаковка: ${name}`;
    result.prepend(photo);
  }
  appendProductSection(result, 'Состав', ingredients || 'Состав не указан в базе данных.');

  const allergens = product.allergens || readableTags(product.allergens_tags || product.allergens_hierarchy);
  const allergenSection = appendProductSection(
    result,
    'Аллергены',
    allergens || 'Аллергены не указаны в базе. Это не подтверждает, что продукт не содержит аллергенов.',
    allergens ? 'product-warning' : 'product-caution',
  );
  allergenSection.classList.add('allergen-section');

  const additives = getAdditives(product);
  appendProductSection(result, 'Добавки и консерванты', additives.text, additives.known ? '' : 'product-caution');
  if (product.nutriscore_grade) {
    const score = document.createElement('p');
    score.className = 'product-score';
    score.textContent = `Nutri-Score: ${product.nutriscore_grade.toUpperCase()}`;
    result.append(score);
  }
  const barcode = document.createElement('p');
  barcode.className = 'product-barcode';
  barcode.textContent = `Штрихкод: ${code}`;
  result.append(barcode);
  productContent.replaceChildren(result);
}

function appendProductSection(parent, heading, content, className = '') {
  const section = document.createElement('section');
  section.className = `product-info-section ${className}`.trim();
  const title = document.createElement('h4');
  title.textContent = heading;
  const text = document.createElement('p');
  text.textContent = content;
  section.append(title, text);
  parent.append(section);
  return section;
}

function readableTags(tags = []) {
  return tags.map((tag) => tag.replace(/^[a-z]{2}:/i, '').replace(/-/g, ' ')).join(', ');
}

function getAdditives(product) {
  const tags = [...new Set(product.additives_original_tags?.length
    ? product.additives_original_tags
    : (product.additives_tags || []))];
  const count = Number.isFinite(product.additives_n) ? product.additives_n : null;
  if (!tags.length && count === 0) {
    return { known: true, text: 'В базе добавки не отмечены. Сверяйте это с составом на упаковке.' };
  }
  if (!tags.length) {
    return { known: false, text: count ? `В базе отмечено добавок: ${count}, но их список не заполнен.` : 'Сведения о добавках и консервантах не указаны в базе.' };
  }

  const additiveIngredients = [];
  function collectAdditives(items = []) {
    for (const item of items) {
      if (item.additive_class || /^en:e\d/i.test(item.id || '')) additiveIngredients.push(item);
      if (Array.isArray(item.ingredients)) collectAdditives(item.ingredients);
    }
  }
  collectAdditives(product.ingredients || []);
  const preservativeCodes = new Set(additiveIngredients
    .filter((item) => /preserv|conserv/i.test(item.additive_class || ''))
    .map((item) => item.id?.replace(/^.*:/, '').toUpperCase())
    .filter(Boolean));
  const descriptions = tags.map((tag) => {
    const code = tag.match(/e\d+[a-z]?/i)?.[0]?.toUpperCase();
    const taxonomyName = tag.replace(/^[a-z]{2}:/i, '').replace(/-/g, ' ');
    const isPreservative = code && preservativeCodes.has(code);
    return `${code || taxonomyName}${isPreservative ? ' — консервант' : ''}`;
  });
  const preservativeTags = descriptions.filter((entry) => entry.includes('— консервант'));
  const otherTags = descriptions.filter((entry) => !entry.includes('— консервант'));
  const lines = [];
  lines.push(preservativeTags.length
    ? `Консерванты: ${preservativeTags.join(', ')}.`
    : 'Консерванты отдельно не отмечены в базе.');
  if (otherTags.length) lines.push(`Другие добавки (это не обязательно консерванты): ${otherTags.join(', ')}.`);
  return { known: true, text: lines.join('\n') };
}

function renderNotFound(code) {
  const message = document.createElement('section');
  message.className = 'product-result empty-result';
  const title = document.createElement('h3');
  title.textContent = 'Продукт пока не найден';
  const text = document.createElement('p');
  text.textContent = `Штрихкод ${code} прочитан, но такого продукта пока нет в базе.`;
  message.append(title, text);
  productContent.replaceChildren(message);
}

function renderLookupError(code) {
  const message = document.createElement('section');
  message.className = 'product-result empty-result';
  const title = document.createElement('h3');
  title.textContent = 'Штрихкод успешно считан';
  const text = document.createElement('p');
  text.textContent = `${code}. Не удалось загрузить информацию. Проверьте подключение к интернету.`;
  message.append(title, text);
  productContent.replaceChildren(message);
}

function stopCamera() {
  scanning = false;
  window.clearTimeout(scanTimer);
  window.clearTimeout(fallbackTimer);
  zxingReader = null;
  rotationCanvas = null;
  rotationContext = null;
  if (stream) stream.getTracks().forEach((track) => track.stop());
  torchOn = false;
  torchButton.hidden = true;
  stream = null;
  video.srcObject = null;
  cameraFrame.classList.remove('is-active');
  cameraMessage.hidden = false;
  hint.hidden = false;
  switchButton.hidden = true;
  if (!productView.hidden) productContent.replaceChildren();
}

async function toggleTorch() {
  const track = stream?.getVideoTracks()[0];
  if (!track || !track.getCapabilities?.().torch) return;
  try {
    torchOn = !torchOn;
    await track.applyConstraints({ advanced: [{ torch: torchOn }] });
    torchButton.textContent = torchOn ? 'Выключить фонарик' : 'Включить фонарик';
    torchButton.setAttribute('aria-pressed', String(torchOn));
  } catch {
    torchOn = false;
    torchButton.textContent = 'Фонарик недоступен';
    torchButton.setAttribute('aria-pressed', 'false');
  }
}

function openScanner() {
  productContent.replaceChildren();
  scanView.hidden = false;
  productView.hidden = true;
  scanner.classList.add('is-open');
  scanner.setAttribute('aria-hidden', 'false');
  document.body.style.overflow = 'hidden';
  closeButton.focus();
  startCamera();
}

function closeScanner() {
  stopCamera();
  scanner.classList.remove('is-open');
  scanner.setAttribute('aria-hidden', 'true');
  scanView.hidden = false;
  productView.hidden = true;
  document.body.style.overflow = '';
  startButton.focus();
}

function returnToScanner() {
  productView.hidden = true;
  scanView.hidden = false;
  startCamera();
}

startButton.addEventListener('click', openScanner);
closeButton.addEventListener('click', closeScanner);
closeProductButton.addEventListener('click', closeScanner);
scanAgainButton.addEventListener('click', returnToScanner);
torchButton.addEventListener('click', toggleTorch);
switchButton.addEventListener('click', () => {
  facingMode = facingMode === 'environment' ? 'user' : 'environment';
  startCamera();
});
scanner.addEventListener('click', (event) => { if (event.target === scanner) closeScanner(); });
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && scanner.classList.contains('is-open')) closeScanner();
});
