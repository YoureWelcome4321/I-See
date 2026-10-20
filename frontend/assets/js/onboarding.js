(() => {
  const steps = [
    { kicker: "ПЕРВОЕ ЗНАКОМСТВО", title: "Покупки спокойнее", text: "Я Вижу! помогает разобраться в составе продуктов, аллергенах и добавках простыми словами." },
    { kicker: "НАСТРОЙТЕ ПОД СЕБЯ", title: "Читайте как удобно", text: "Выберите размер текста. Его можно изменить позже в настройках профиля." },
    { kicker: "ВАШ ПРОФИЛЬ", title: "Сохраним важное", text: "Укажите имя, телефон и продукты, которые важно учитывать при проверке." },
  ];
  const storageKey = "ya-vizhu-medical-card-v1";
  const legacyStorageKey = "ya-vizhu-onboarding-restrictions";
  let phoneCheckTimer;
  let phoneCheckInFlight;
  let phoneCheckValue = "";
  let phoneCheckSequence = 0;
  let step = 0;
  const $ = (id) => document.getElementById(id);

  function normalizeRestrictions(value) {
    if (!Array.isArray(value)) return [];
    const seen = new Set();
    return value.reduce((result, item) => {
      if (!item || !["allergy", "avoid"].includes(item.type)) return result;
      const name = String(item.name || item.food || "").trim().slice(0, 80);
      if (!name) return result;
      const key = `${item.type}:${name.toLocaleLowerCase("ru")}`;
      if (seen.has(key)) return result;
      seen.add(key);
      result.push({ type: item.type, name });
      return result;
    }, []);
  }

  function readSavedRestrictions() {
    try {
      const current = normalizeRestrictions(JSON.parse(localStorage.getItem(storageKey) || "null"));
      if (current.length) return current;
      return normalizeRestrictions(JSON.parse(localStorage.getItem(legacyStorageKey) || "null"));
    } catch {
      return [];
    }
  }

  function render() {
    const data = steps[step];
    $("onboarding-kicker").textContent = data.kicker;
    $("onboarding-title").textContent = data.title;
    $("onboarding-description").textContent = data.text;
    document.querySelectorAll("[data-step-art]").forEach((node) => { node.hidden = Number(node.dataset.stepArt) !== step; });
    document.querySelectorAll(".onboarding-step[data-step]").forEach((node) => { node.hidden = Number(node.dataset.step) !== step; });
    $("onboarding-back").hidden = step === 0;
    $("onboarding-next").querySelector("span").textContent = step === steps.length - 1 ? "Создать профиль" : "Далее";
    $("onboarding-counter").textContent = `${step + 1} из ${steps.length}`;
    const progress = ((step + 1) / steps.length) * 100;
    $("onboarding-progress-fill").style.width = `${progress}%`;
    $("onboarding-progress").setAttribute("aria-valuenow", String(step + 1));
    $("onboarding-progress").setAttribute("aria-valuetext", `Шаг ${step + 1} из ${steps.length}`);
    document.querySelector(".onboarding-card").dataset.step = String(step);
    $("onboarding-status").textContent = "";
  }

  function hydrateRestrictions() {
    const saved = readSavedRestrictions();
    const restriction = saved[0];
    $("onboarding-restriction").value = restriction?.name || "";
  }

  function getRestrictions() {
    const value = $("onboarding-restriction").value.trim();
    return value ? [{ type: "avoid", name: value.slice(0, 80) }] : [];
  }

  function setFieldError(id, message) {
    const input = $(id);
    const error = $(`${id}-error`);
    input.classList.toggle("invalid", Boolean(message));
    input.setAttribute("aria-invalid", message ? "true" : "false");
    if (error) error.textContent = message || "";
  }

  function validateName() {
    const value = $("onboarding-name").value.trim();
    const valid = value.length >= 2 && value.length <= 80 && !/[\d<>]/.test(value);
    setFieldError("onboarding-name", valid || !value ? "" : "Введите корректное имя (минимум 2 символа).");
    return valid;
  }

  function validatePhoneFormat() {
    const input = $("onboarding-phone");
    const raw = input.value.trim();
    const digits = raw.replace(/\D/g, "");
    const valid = /^\+?[\d\s().-]+$/.test(raw) && digits.length >= 10 && digits.length <= 15;
    setFieldError("onboarding-phone", valid || !digits ? "" : "Введите номер от 10 до 15 цифр.");
    return valid;
  }

  function validatePassword() {
    const value = $("onboarding-password").value;
    const valid = value.length >= 6 && value.length <= 128;
    setFieldError("onboarding-password", valid || !value ? "" : "Пароль должен быть не короче 6 символов.");
    return valid;
  }

  async function checkPhoneAvailability() {
    if (!validatePhoneFormat()) return false;
    const phone = $("onboarding-phone").value.trim();
    if (phoneCheckValue === phone && phoneCheckInFlight) return phoneCheckInFlight;
    const sequence = ++phoneCheckSequence;
    phoneCheckValue = phone;
    phoneCheckInFlight = window.YaVizhuAPI.checkPhone(phone).then((result) => {
      if (sequence !== phoneCheckSequence || $("onboarding-phone").value.trim() !== phone) return false;
      if (!result.available) setFieldError("onboarding-phone", "Этот номер уже зарегистрирован.");
      else setFieldError("onboarding-phone", "");
      return result.available;
    }).catch((error) => {
      if (sequence !== phoneCheckSequence || $("onboarding-phone").value.trim() !== phone) return false;
      setFieldError("onboarding-phone", error.message || "Не удалось проверить номер.");
      return false;
    });
    return phoneCheckInFlight;
  }

  async function finish() {
    const name = $("onboarding-name").value.trim();
    const phone = $("onboarding-phone").value.trim();
    const status = $("onboarding-status");
    if (!validateName()) {
      status.textContent = "Проверьте имя.";
      $("onboarding-name").focus();
      return;
    }
    if (!validatePhoneFormat()) {
      status.textContent = "Проверьте номер телефона.";
      $("onboarding-phone").focus();
      return;
    }
    if (!validatePassword()) {
      status.textContent = "Придумайте пароль не короче 6 символов.";
      $("onboarding-password").focus();
      return;
    }
    const phoneAvailable = await (phoneCheckValue === phone && phoneCheckInFlight ? phoneCheckInFlight : checkPhoneAvailability());
    if (!phoneAvailable) { $("onboarding-phone").focus(); return; }

    const nextButton = $("onboarding-next");
    nextButton.disabled = true;
    nextButton.setAttribute("aria-busy", "true");
    status.textContent = "Создаём профиль…";
    try {
      const restrictions = getRestrictions();
      await window.YaVizhuAPI.register(name, phone, $("onboarding-password").value, restrictions);
      const fontSize = document.querySelector('input[name="font-size"]:checked')?.value || "normal";
      localStorage.setItem("ya-vizhu-onboarding-done-v1", "1");
      localStorage.setItem("ya-vizhu-font-size", fontSize);
      localStorage.setItem(storageKey, JSON.stringify(restrictions));
      localStorage.removeItem(legacyStorageKey);
      document.documentElement.dataset.fontSize = fontSize;
      // The onboarding page is served at /onboarding.html; always return to
      // the site root after account creation, regardless of the current URL.
      window.location.assign("/");
    } catch (error) {
      status.textContent = error.message || "Не удалось создать профиль. Попробуйте ещё раз.";
      nextButton.disabled = false;
      nextButton.removeAttribute("aria-busy");
    }
  }

  $("onboarding-next").addEventListener("click", () => {
    if (step === steps.length - 1) finish();
    else { step += 1; render(); }
  });
  $("onboarding-back").addEventListener("click", () => { step = Math.max(0, step - 1); render(); });
  $("onboarding-name").addEventListener("blur", validateName);
  $("onboarding-phone").addEventListener("blur", checkPhoneAvailability);
  $("onboarding-password").addEventListener("blur", validatePassword);
  $("onboarding-phone").addEventListener("input", () => {
    clearTimeout(phoneCheckTimer);
    validatePhoneFormat();
    phoneCheckInFlight = null;
    phoneCheckValue = "";
    phoneCheckSequence += 1;
    phoneCheckTimer = setTimeout(checkPhoneAvailability, 450);
  });
  hydrateRestrictions();
  render();
})();
