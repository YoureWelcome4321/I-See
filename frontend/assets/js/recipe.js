(() => {
  const root = document.querySelector('#recipe');
  const id = new URLSearchParams(location.search).get('id');
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  if (!id) { root.innerHTML = '<p>Рецепт не найден.</p>'; return; }
  fetch(`/api/recipes/${encodeURIComponent(id)}`).then((r) => r.ok ? r.json() : Promise.reject(new Error('Рецепт не найден.'))).then((recipe) => {
    root.innerHTML = `<section class="recipe-hero"><img src="/assets/images/${esc(recipe.image)}" alt=""><div class="recipe-copy"><h1>${esc(recipe.title)}</h1><p>${esc(recipe.description)}</p>${recipe.sponsored_product ? `<div class="recipe-ad">${esc(recipe.sponsored_label || 'РЕКЛАМНЫЙ ПРОДУКТ')}: ${esc(recipe.sponsored_product)}</div>` : ''}</div></section><section class="recipe-section"><h2>Ингредиенты</h2><ul>${recipe.ingredients.map((x) => `<li>${esc(x)}</li>`).join('')}</ul></section><section class="recipe-section"><h2>Приготовление</h2><ol>${recipe.steps.map((x) => `<li>${esc(x)}</li>`).join('')}</ol></section>`;
    document.title = `${recipe.title} — Я Вижу!`;
  }).catch((error) => { root.innerHTML = `<p>${esc(error.message)}</p>`; });
})();
