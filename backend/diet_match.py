"""Which products and recipes clash with a person's "can't eat" list.

Two layers: word rules answer instantly (milk also catches kefir, cottage cheese,
butter...), and a language model looks for less obvious matches in the background.
The model may only add matches, never clear what the rules found, so a hidden
product never reappears because the model was unsure.
"""
import hashlib
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor

try:
    from free_search import ALLERGEN_STEMS, DEFAULT_FREE_MODELS, _first_json_object, _http
except ImportError:  # imported as backend.diet_match
    from backend.free_search import ALLERGEN_STEMS, DEFAULT_FREE_MODELS, _first_json_object, _http

# Extra everyday words people use for the same allergen groups.
EXTRA_STEMS = {
    "молоко": ("сгущ", "масло сливоч", "сливочное масло", "ряженк", "простокваш", "пломбир", "мороже", "моцарел", "пармез", "брынз", "фета"),
    "глютен": ("мука", "муки", "манк", "макарон", "спагетти", "хлеб", "батон", "булк", "круассан", "печень", "вафл", "кускус", "булгур"),
    "яйца": ("майонез", "безе", "меренг"),
    "рыба": ("горбуш", "сельд", "скумбр", "кета", "сёмг", "семг", "форел", "минта", "хек"),
    "орехи": ("грецк", "кедров", "пралине", "нутелл"),
    "сахар": ("сахар", "сироп", "мёд", "мед ", "сгущ", "варень", "шоколад", "мармелад", "зефир", "карамел", "фруктоз", "глюкоз", "декстроз"),
}
# Names people type for a group ("яйцо", "молочное") point to that group.
GROUP_ALIASES = {
    "молок": "молоко", "молоч": "молоко", "лактоз": "молоко",
    "глютен": "глютен", "пшени": "глютен", "клейковин": "глютен",
    "яйц": "яйца", "яйцо": "яйца",
    "орех": "орехи", "рыб": "рыба", "соя": "соя", "сои": "соя", "соев": "соя",
    "сахар": "сахар", "сладк": "сахар",
}
AI_TIMEOUT = 40
BATCH_SIZE = 25

_running = set()
_running_lock = threading.Lock()
_pool = ThreadPoolExecutor(max_workers=2)


def _norm(text):
    return f" {str(text or '').casefold().replace('ё', 'е')} "


def _group(name):
    low = _norm(name).strip()
    for alias, group in GROUP_ALIASES.items():
        if low.startswith(alias.replace("ё", "е")):
            return group
    return None


def patterns_for(name):
    """Regexes that mean this restriction is in the text; each starts at a word start."""
    group = _group(name)
    stems = set()
    if group:
        stems.update(ALLERGEN_STEMS.get(group, ()))
        stems.update(EXTRA_STEMS.get(group, ()))
    patterns = {rf"(?<!\w){re.escape(stem.strip().replace('ё', 'е'))}" for stem in stems if stem.strip()}
    # The typed word itself: long words by stem ("орехи" finds "орехами"), short ones
    # only with a short ending ("мёд" finds "мёдом", not "медленно").
    for word in re.findall(r"\w+", name.casefold().replace("ё", "е")):
        if len(word) > 4:
            patterns.add(rf"(?<!\w){re.escape(word[:-1])}")
        else:
            patterns.add(rf"(?<!\w){re.escape(word)}\w{{0,2}}(?!\w)")
    return patterns


def rule_matches(restrictions, text):
    low = _norm(text)
    return [name for name in restrictions if any(re.search(pattern, low) for pattern in patterns_for(name))]


def _cache_key(restrictions, text):
    digest = hashlib.sha256(json.dumps([sorted(r.casefold() for r in restrictions), text.casefold()], ensure_ascii=False).encode()).hexdigest()
    return f"diet:{digest}"


def ai_enabled():
    return bool(os.getenv("OPENROUTER_API_KEY", "").strip()) and os.getenv("DIET_AI", "1") != "0"


def _ask_model(restrictions, items):
    """One request for a batch: {item_id: [restriction, ...]} or None if no model answered."""
    prompt = {
        "restrictions": restrictions,
        "items": [{"id": item_id, "text": text} for item_id, text in items],
        "task": "Человеку нельзя есть продукты из restrictions (аллергия или не ест). Для каждого item определи, какие из restrictions в нём есть, "
                "включая производные и скрытые формы: молоко — сливочное масло, сыр, сгущёнка, сыворотка; глютен — пшеничная мука, манка; "
                "яйца — майонез, яичный порошок и т. п. Используй только названия из restrictions. Если сомневаешься, лучше отметь. "
                'Ответ — один JSON-объект {"id предмета": ["ограничение", ...]}; предметы без совпадений не включай.',
    }
    models = [m.strip() for m in os.getenv("OPENROUTER_FREE_MODELS", DEFAULT_FREE_MODELS).split(",") if m.strip()]
    paid = os.getenv("OPENROUTER_MODEL", "").strip()
    if paid and paid not in models:
        models.append(paid)
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    for model in models:
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": "Ты помогаешь людям с пищевыми ограничениями. Отвечай только JSON."},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            "temperature": 0,
            "max_tokens": 1200,
            "reasoning": {"effort": "low"},
        }
        try:
            _, payload = _http("https://openrouter.ai/api/v1/chat/completions", data=json.dumps(body).encode(),
                               headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "X-Title": "I-See Food Assistant"}, timeout=AI_TIMEOUT)
            content = json.loads(payload)["choices"][0]["message"].get("content") or ""
            answer = _first_json_object(content)
            if answer is not None:
                return answer
            print(f"Diet AI {model}: answer without JSON", flush=True)
        except Exception as error:
            print(f"Diet AI {model}: {type(error).__name__}: {error}", flush=True)
    return None


def _run_batch(restrictions, items, write_cache):
    answer = _ask_model(restrictions, items)
    allowed = {name.casefold(): name for name in restrictions}
    for item_id, text in items:
        found = answer.get(str(item_id), []) if isinstance(answer, dict) else None
        if found is None:
            continue  # no model answered: leave it uncached so a later visit retries
        matches = [allowed[x.casefold()] for x in found if isinstance(x, str) and x.casefold() in allowed] if isinstance(found, list) else []
        write_cache(_cache_key(restrictions, text), {"matches": matches})


def _background(restrictions, items, write_cache, job):
    try:
        for start in range(0, len(items), BATCH_SIZE):
            _run_batch(restrictions, items[start:start + BATCH_SIZE], write_cache)
    finally:
        with _running_lock:
            _running.discard(job)


def check(restrictions, items, read_cache, write_cache):
    """items: [(id, text)]. Returns ({id: [matches]}, ai_state) where ai_state is done/pending/off."""
    restrictions = [r for r in dict.fromkeys(str(x).strip() for x in restrictions) if r]
    results, missing = {}, []
    for item_id, text in items:
        matches = rule_matches(restrictions, text) if restrictions else []
        if restrictions and ai_enabled():
            cached = read_cache(_cache_key(restrictions, text))
            if cached is None:
                missing.append((item_id, text))
            else:
                matches += [m for m in cached.get("matches", []) if m not in matches]
        results[item_id] = matches
    if not restrictions or not ai_enabled():
        return results, "off"
    if not missing:
        return results, "done"
    job = _cache_key(restrictions, "\n".join(text for _, text in missing))
    with _running_lock:
        if job not in _running:
            _running.add(job)
            _pool.submit(_background, restrictions, missing, write_cache, job)
    return results, "pending"
