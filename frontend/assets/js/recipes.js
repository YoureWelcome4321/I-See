(() => {
  const grid = document.querySelector('#recipe-grid');
  const status = document.querySelector('#recipe-status');
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const recipeWord = (n) => {
    const m = n % 10, h = n % 100;
    if (m === 1 && h !== 11) return 'рецепт';
    if (m >= 2 && m <= 4 && (h < 12 || h > 14)) return 'рецепта';
    return 'рецептов';
  };
  let recipes = [];

  function render(list) {
    grid.innerHTML = list.map((r) => `<article class="recipe-card"><img src="/assets/images/${esc(r.image)}" alt=""><div class="recipe-card-body"><h2>${esc(r.title)}</h2><p>${esc(r.description)}</p>${r.sponsored_product ? `<p><small>${esc(r.sponsored_label || 'Рекламный продукт')}: ${esc(r.sponsored_product)}</small></p>` : ''}<a class="ui-btn ui-btn--ghost ui-btn--sm ui-btn--block" href="/recipe.html?id=${encodeURIComponent(r.id)}"><span>Открыть рецепт</span><i aria-hidden="true">→</i></a></div></article>`).join('');
  }

  // Word rules answer at once; the neural network finishes in the background, so ask again while it works.
  async function checkDiet(attempt) {
    const data = await YaVizhuAPI.request('/api/diet/check', {
      method: 'POST',
      body: JSON.stringify({ items: recipes.map((r) => ({ id: r.id, text: `${r.title}: ${r.ingredients.join(', ')}` })) }),
    });
    if (!data.restrictions.length) { render(recipes); status.textContent = `Доступно рецептов: ${recipes.length}`; return; }
    const allowed = recipes.filter((r) => !(data.results[r.id] || []).length);
    const hidden = recipes.length - allowed.length;
    render(allowed);
    let text = hidden
      ? `Подобрали ${allowed.length} ${recipeWord(allowed.length)} под ваш список «${data.restrictions.join(', ')}». Ещё ${hidden} ${recipeWord(hidden)} мы убрали.`
      : `Все рецепты подходят под ваш список «${data.restrictions.join(', ')}».`;
    if (data.ai === 'pending') text += ' Нейросеть ещё уточняет состав — список может немного измениться.';
    status.textContent = text;
    if (data.ai === 'pending' && attempt < 8) setTimeout(() => checkDiet(attempt + 1).catch(() => {}), 4000);
  }

  async function run() {
    try {
      recipes = await YaVizhuAPI.request('/api/recipes');
      // A signed-in person never sees, even for a moment, a dish they can't eat.
      if (YaVizhuAPI.hasToken()) {
        status.textContent = 'Подбираем рецепты под ваш профиль…';
        try { await checkDiet(0); return; } catch { /* fall back to the full list */ }
      }
      render(recipes);
      status.textContent = `Доступно рецептов: ${recipes.length}`;
    } catch (error) {
      status.textContent = error.message || 'Не удалось загрузить рецепты.';
    }
  }
  run();
})();
