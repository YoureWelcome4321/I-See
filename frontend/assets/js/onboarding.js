(() => {
  const STEP_COUNT = 4;
  const COMMON_FOODS = ["молоко", "яйца", "орехи", "арахис", "глютен", "рыба", "соя", "сахар"];
  const storageKey = "ya-vizhu-medical-card-v1";
  const legacyStorageKey = "ya-vizhu-onboarding-restrictions";
  const doneKey = "ya-vizhu-onboarding-done-v1";
  const fontSizeKey = "ya-vizhu-font-size";
  let phoneCheckTimer;
  let phoneCheckInFlight;
  let phoneCheckValue = "";
  let phoneCheckSequence = 0;
  let step = 0;
  let fontSize = localStorage.getItem(fontSizeKey) === "large" ? "large" : "normal";
  const $ = (id) => document.getElementById(id);
  const stepNodes = [...document.querySelectorAll(".onboarding-step[data-step]")];
  const dots = [...document.querySelectorAll(".onboarding-dots i")];

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

  // Chosen foods, keyed by lower-case name so "Мёд" and "мёд" are one button.
  const chosen = new Map(readSavedRestrictions().map((item) => [item.name.toLocaleLowerCase("ru"), item]));

  function render() {
    stepNodes.forEach((node) => { node.hidden = Number(node.dataset.step) !== step; });
    dots.forEach((dot, index) => dot.classList.toggle("is-done", index <= step));
    // The greeting has nothing to go back to, so its top row would be empty space.
    document.querySelector(".onboarding-top").hidden = step === 0;
    $("onboarding-counter").textContent = step === 0 ? "" : `Шаг ${step + 1} из ${STEP_COUNT}`;
    $("onboarding-status").textContent = "";
    const heading = stepNodes[step].querySelector("h1, h2");
    if (step > 0) heading.focus({ preventScroll: true });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function go(next) {
    step = Math.min(STEP_COUNT - 1, Math.max(0, next));
    render();
  }

  function applyFontSize(size) {
    fontSize = size;
    document.documentElement.dataset.fontSize = size;
    document.querySelectorAll(".onboarding-sizes [data-size]").forEach((button) => button.setAttribute("aria-checked", String(button.dataset.size === size)));
  }

  function renderFoods() {
    const box = $("onboarding-foods");
    const names = [...COMMON_FOODS];
    chosen.forEach((item, key) => { if (!names.includes(key)) names.push(item.name); });
    box.replaceChildren(...names.map((name) => {
      const key = name.toLocaleLowerCase("ru");
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = name.charAt(0).toLocaleUpperCase("ru") + name.slice(1);
      button.setAttribute("aria-pressed", String(chosen.has(key)));
      button.addEventListener("click", () => {
        if (chosen.has(key)) chosen.delete(key); else chosen.set(key, { type: "allergy", name });
        renderFoods();
      });
      return button;
    }));
    $("onboarding-foods-next").textContent = chosen.size ? "Дальше" : "Ничего из этого — дальше";
  }

  function restrictions() {
    return [...chosen.values()];
  }

  // Font size and foods chosen during onboarding stay on the device as well as in the account.
  function rememberChoices() {
    localStorage.setItem(doneKey, "1");
    localStorage.setItem(fontSizeKey, fontSize);
    localStorage.setItem(storageKey, JSON.stringify(restrictions()));
    localStorage.removeItem(legacyStorageKey);
  }

  function setFieldError(id, message) {
    const input = $(id);
    input.setAttribute("aria-invalid", message ? "true" : "false");
    $(`${id}-error`).textContent = message || "";
  }

  function validateName() {
    const value = $("onboarding-name").value.trim();
    const valid = value.length >= 2 && value.length <= 80 && !/[\d<>]/.test(value);
    setFieldError("onboarding-name", valid || !value ? "" : "Напишите имя буквами, хотя бы 2 буквы.");
    return valid;
  }

  function validatePhoneFormat() {
    const raw = $("onboarding-phone").value.trim();
    const digits = raw.replace(/\D/g, "");
    const valid = /^\+?[\d\s().-]+$/.test(raw) && digits.length >= 10 && digits.length <= 15;
    setFieldError("onboarding-phone", valid || !digits ? "" : "Проверьте номер: в нём должно быть 11 цифр.");
    return valid;
  }

  function validatePassword() {
    const value = $("onboarding-password").value;
    const valid = value.length >= 6 && value.length <= 128;
    setFieldError("onboarding-password", valid || !value ? "" : "Пароль слишком короткий — нужно хотя бы 6 знаков.");
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
      setFieldError("onboarding-phone", result.available ? "" : "С этим номером профиль уже есть — нажмите «Войти» ниже.");
      return result.available;
    }).catch((error) => {
      if (sequence !== phoneCheckSequence || $("onboarding-phone").value.trim() !== phone) return false;
      setFieldError("onboarding-phone", error.message || "Не получилось проверить номер.");
      return false;
    });
    return phoneCheckInFlight;
  }

  async function finish(event) {
    event.preventDefault();
    const status = $("onboarding-status");
    const checks = [
      [validateName, "onboarding-name", "Напишите, как вас зовут."],
      [validatePhoneFormat, "onboarding-phone", "Напишите номер телефона."],
      [validatePassword, "onboarding-password", "Придумайте пароль из 6 знаков или больше."],
    ];
    for (const [validate, id, emptyMessage] of checks) {
      if (validate()) continue;
      if (!$(id).value.trim()) setFieldError(id, emptyMessage);
      $(id).focus();
      return;
    }
    const phone = $("onboarding-phone").value.trim();
    const phoneAvailable = await (phoneCheckValue === phone && phoneCheckInFlight ? phoneCheckInFlight : checkPhoneAvailability());
    if (!phoneAvailable) { $("onboarding-phone").focus(); return; }

    const submit = $("onboarding-submit");
    submit.disabled = true;
    submit.setAttribute("aria-busy", "true");
    status.textContent = "Сохраняем профиль…";
    try {
      await window.YaVizhuAPI.register($("onboarding-name").value.trim(), phone, $("onboarding-password").value, restrictions());
      rememberChoices();
      window.location.assign("/");
    } catch (error) {
      status.textContent = error.message || "Не получилось сохранить профиль. Попробуйте ещё раз.";
      submit.disabled = false;
      submit.removeAttribute("aria-busy");
    }
  }

  document.querySelectorAll("[data-next]").forEach((button) => button.addEventListener("click", () => go(step + 1)));
  $("onboarding-back").addEventListener("click", () => go(step - 1));
  document.querySelectorAll(".onboarding-sizes [data-size]").forEach((button) => button.addEventListener("click", () => applyFontSize(button.dataset.size)));
  $("onboarding-other").addEventListener("submit", (event) => {
    event.preventDefault();
    const input = $("onboarding-other-input");
    const name = input.value.trim().slice(0, 80);
    if (name) chosen.set(name.toLocaleLowerCase("ru"), { type: "allergy", name });
    input.value = "";
    renderFoods();
    input.focus();
  });
  $("onboarding-form").addEventListener("submit", finish);
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

  applyFontSize(fontSize);
  renderFoods();
  render();
})();
