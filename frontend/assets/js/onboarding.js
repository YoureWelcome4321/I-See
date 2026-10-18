(() => {
  const steps = [
    { kicker: "ПЕРВОЕ ЗНАКОМСТВО", title: "Покупки спокойнее", text: "Я Вижу! помогает разобраться в составе продуктов, аллергенах и добавках простыми словами." },
    { kicker: "НАСТРОЙТЕ ПОД СЕБЯ", title: "Как вам удобнее читать?", text: "Выберите размер текста. Его можно изменить позже в настройках профиля." },
    { kicker: "ВАША КАРТОЧКА", title: "Расскажите о важном", text: "Добавьте ограничения, чтобы при проверке продукта мы сразу обратили на них внимание." },
  ];
  let step = 0;
  const $ = (id) => document.getElementById(id);
  const render = () => {
    const data = steps[step];
    $("onboarding-kicker").textContent = data.kicker;
    $("onboarding-title").textContent = data.title;
    $("onboarding-description").textContent = data.text;
    document.querySelectorAll("[data-step-art]").forEach((node) => { node.hidden = Number(node.dataset.stepArt) !== step; });
    document.querySelectorAll("[data-step]").forEach((node) => { node.hidden = Number(node.dataset.step) !== step; });
    $("onboarding-back").hidden = step === 0;
    $("onboarding-next").textContent = step === steps.length - 1 ? "Начать пользоваться" : "Далее";
    $("onboarding-counter").textContent = `${step + 1} из ${steps.length}`;
    $("onboarding-progress-fill").style.width = `${((step + 1) / steps.length) * 100}%`;
  };
  const finish = () => {
    const restrictions = [];
    const allergy = $("onboarding-allergy").value.trim();
    const avoid = $("onboarding-avoid").value.trim();
    if (allergy) restrictions.push({ type: "allergy", food: allergy });
    if (avoid) restrictions.push({ type: "avoid", food: avoid });
    localStorage.setItem("ya-vizhu-onboarding-done-v1", "1");
    localStorage.setItem("ya-vizhu-font-size", document.querySelector('input[name="font-size"]:checked')?.value || "normal");
    localStorage.setItem("ya-vizhu-onboarding-restrictions", JSON.stringify(restrictions));
    document.documentElement.dataset.fontSize = document.querySelector('input[name="font-size"]:checked')?.value || "normal";
    window.location.href = "index.html";
  };
  $("onboarding-next").addEventListener("click", () => { if (step === steps.length - 1) finish(); else { step += 1; render(); } });
  $("onboarding-back").addEventListener("click", () => { step = Math.max(0, step - 1); render(); });
  $("onboarding-skip").addEventListener("click", finish);
  render();
})();
