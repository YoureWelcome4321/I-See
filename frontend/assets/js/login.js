(() => {
  const storageKey = "ya-vizhu-medical-card-v1";
  const form = document.getElementById("login-form");
  const phone = document.getElementById("login-phone");
  const password = document.getElementById("login-password");
  const error = document.getElementById("login-error");
  const submit = document.getElementById("login-submit");
  const params = new URLSearchParams(window.location.search);
  // Only same-site paths are allowed as the return address.
  const next = /^\/(?![\/\\])/.test(params.get("next") || "") ? params.get("next") : "/";

  if (window.YaVizhuAPI.hasToken()) { window.location.replace(next); return; }
  if (params.has("expired")) error.textContent = "Время входа истекло. Войдите ещё раз.";

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!phone.value.trim()) { error.textContent = "Напишите номер телефона."; phone.focus(); return; }
    if (!password.value) { error.textContent = "Напишите пароль."; password.focus(); return; }
    error.textContent = "";
    submit.disabled = true;
    submit.setAttribute("aria-busy", "true");
    try {
      await window.YaVizhuAPI.login(phone.value.trim(), password.value);
      // A returning user on a new device should not be sent back to onboarding.
      localStorage.setItem("ya-vizhu-onboarding-done-v1", "1");
      const profile = await window.YaVizhuAPI.request("/api/profile");
      localStorage.setItem(storageKey, JSON.stringify(profile.restrictions || []));
      window.location.assign(next);
    } catch (problem) {
      // The server speaks of a "login" the person never saw; keep it to phone and password.
      error.textContent = /^Неверный/.test(problem.message || "") ? "Номер или пароль не подходят. Проверьте и попробуйте ещё раз." : problem.message || "Не получилось войти. Попробуйте ещё раз.";
      submit.disabled = false;
      submit.removeAttribute("aria-busy");
    }
  });
})();
