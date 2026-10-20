"""Free product lookup: web search by product name, page reading and grounded extraction.

Search uses Tavily (free monthly plan, official API) when TAVILY_API_KEY is set,
otherwise the DuckDuckGo HTML page as a best-effort fallback that backs off as soon
as it shows a bot check. Extraction tries free OpenRouter models first and falls
back to plain rules. Every value has to be traceable to the text of a page that
mentions the product; anything the model adds on its own is dropped.
"""
import html
import json
import os
import re
import ssl
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlencode, urlparse
from urllib.request import Request, urlopen

import certifi

TLS_CONTEXT = ssl.create_default_context(cafile=certifi.where())
BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
SUPPORTED_FIELDS = ("ingredients", "allergens", "additives", "nutrition")
DEFAULT_FREE_MODELS = "minimax/minimax-m3.1-flash:free,openrouter/free"
SKIP_HOSTS = ("openfoodfacts.org", "youtube.com", "vk.com", "t.me", "instagram.com")
PAGE_TEXT_LIMIT = 1500
TOTAL_TEXT_LIMIT = 4500

_ddg_lock = threading.Lock()
_ddg_blocked_until = 0.0

# Allergen groups the EU/EAEU labelling rules require; stems are matched in lowercase text.
ALLERGEN_STEMS = {
    "молоко": ("молок", "молоч", "сливк", "сливоч", "сыворот", "лактоз", "казеин", "творог", "сыр ", "кефир", "йогурт", "сметан"),
    "глютен": ("глютен", "пшени", "рож", "ячмен", "овс", "полба", "солод"),
    "яйца": ("яйц", "яичн", "меланж"),
    "орехи": ("орех", "фундук", "миндал", "кешью", "фисташ", "пекан"),
    "арахис": ("арахис",),
    "соя": ("соя", "соев"),
    "рыба": ("рыб", "лосос", "тунец", "треск", "анчоус"),
    "ракообразные": ("кревет", "краб", "омар", "лангуст"),
    "моллюски": ("моллюск", "мидии", "кальмар", "устриц"),
    "кунжут": ("кунжут",),
    "горчица": ("горчиц",),
    "сельдерей": ("сельдер",),
    "люпин": ("люпин",),
    "сульфиты": ("сульфит", "диоксид серы", "e220", "е220", "e221", "е221", "e223", "е223", "e224", "е224"),
}


class SearchUnavailable(Exception):
    """Raised when no search backend can answer right now."""


def _http(url, data=None, headers=None, timeout=10, limit=1_500_000):
    request = Request(url, data=data, headers={"User-Agent": BROWSER_UA, "Accept-Language": "ru-RU,ru;q=0.9", **(headers or {})}, method="POST" if data is not None else "GET")
    with urlopen(request, timeout=timeout, context=TLS_CONTEXT) as response:
        raw = response.read(limit)
        return response.status, raw.decode(response.headers.get_content_charset() or "utf-8", "replace")


def page_text(raw_html):
    """Visible text plus inline JSON strings (shops often keep the description there)."""
    raw = re.sub(r"(?is)<(style|noscript|svg|template)[^>]*>.*?</\1>", " ", raw_html)
    scripts = " ".join(re.findall(r"(?is)<script[^>]*>(.*?)</script>", raw))
    raw = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|td|dd|dt|h\d)>", "\n", raw)
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    scripts = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), scripts)
    scripts = html.unescape(re.sub(r"<[^>]+>", " ", scripts.replace("\\n", "\n").replace('\\"', '"')))
    combined = text + "\n" + scripts
    return re.sub(r"[ \t\xa0]+", " ", combined)


def search_tavily(query, api_key):
    body = {"query": query, "search_depth": "basic", "max_results": 6, "include_raw_content": "text"}
    for attempt in (1, 2):
        try:
            _, payload = _http("https://api.tavily.com/search", data=json.dumps(body).encode(), headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, timeout=25)
            break
        except HTTPError as error:
            raise SearchUnavailable(f"Tavily HTTP {error.code}")
        except (URLError, TimeoutError, OSError) as error:
            if attempt == 2:
                raise SearchUnavailable(f"Tavily недоступен: {error}")
            print(f"Tavily: {error}; retrying once", flush=True)
    results = []
    for item in json.loads(payload).get("results") or []:
        text = item.get("raw_content") or ""
        # Tavily often returns only a short snippet; then the page is downloaded by us.
        results.append({"url": item.get("url", ""), "title": item.get("title") or "", "text": text if len(text) >= 500 else None, "snippet_hint": item.get("content") or ""})
    return results


def tavily_extract(urls, api_key):
    """Page text through Tavily's own crawler, for shops that block plain downloads (1 credit per 5 pages)."""
    try:
        _, payload = _http("https://api.tavily.com/extract", data=json.dumps({"urls": urls[:5], "extract_depth": "basic"}).encode(), headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, timeout=30)
    except Exception as error:
        print(f"Tavily extract: {type(error).__name__}: {error}", flush=True)
        return {}
    return {item.get("url"): item.get("raw_content") or "" for item in json.loads(payload).get("results") or []}


def search_duckduckgo(query):
    """Result links from the DuckDuckGo HTML page; pauses for 15 minutes after a bot check."""
    global _ddg_blocked_until
    with _ddg_lock:
        if time.time() < _ddg_blocked_until:
            raise SearchUnavailable("DuckDuckGo временно ограничил запросы")
    try:
        status, body = _http("https://html.duckduckgo.com/html/", data=urlencode({"q": query, "kl": "ru-ru"}).encode(), timeout=12)
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise SearchUnavailable(f"DuckDuckGo недоступен: {error}")
    if status == 202 or "anomaly" in body.lower():
        with _ddg_lock:
            _ddg_blocked_until = time.time() + 15 * 60
        raise SearchUnavailable("DuckDuckGo показал проверку на робота")
    links = []
    for href, title in re.findall(r'class="result__a" href="([^"]+)"[^>]*>(.*?)</a>', body):
        match = re.search(r"uddg=([^&]+)", href)
        url = unquote(match.group(1)) if match else html.unescape(href)
        links.append({"url": url, "title": html.unescape(re.sub(r"<[^>]+>", "", title)).strip(), "text": None})
    return links


def fetch_page(result):
    if result["text"] is not None:
        return result
    try:
        _, raw = _http(result["url"], timeout=8)
    except Exception:
        # Many shops block plain downloads; keep the page so Tavily can read it instead.
        return {**result, "text": result.get("snippet_hint") or "", "blocked": True}
    return {**result, "text": page_text(raw)}


GENERIC_WORDS = {"продукт", "упаковка", "штук", "товар", "новый", "классический", "натуральный", "смотка"}


def _stems(value):
    # Short prefixes so «яблоко» and «яблочный» match; volumes and numbers are ignored.
    return [w[:4] for w in re.findall(r"[a-zа-яё]{3,}", value.casefold()) if w not in GENERIC_WORDS and w not in ("для", "без")]


# Product types: a page about a nectar must not fill in the label of a juice of the same brand.
PRODUCT_TYPES = ("сок", "нект", "морс", "напи", "вода", "лимо", "чай", "кофе", "како", "моло", "кефи", "йогу", "смет",
                 "твор", "сыр", "масл", "майо", "кетч", "соус", "шоко", "конф", "драж", "бато", "пече", "ваф", "торт",
                 "чипс", "суха", "орех", "лапш", "мака", "круп", "каша", "мюсл", "хлеб", "колб", "соси", "ветч", "пель", "мороже")


# Flavours: «Сок J7 яблоко-персик» is another product than «Сок J7 яблоко».
FLAVOURS = ("перс", "апел", "вишн", "абри", "груш", "анан", "муль", "тома", "вино", "манг", "клуб", "мали",
            "бана", "грей", "гран", "смор", "клюк", "брус", "коко", "кара", "вани", "мята", "мятн", "лайм")


def product_type(stems):
    return next((t for stem in stems for t in PRODUCT_TYPES if stem.startswith(t) or t.startswith(stem) and len(stem) >= 3), None)


def is_about_product(page, barcode, brand, name):
    """A page counts if it shows this barcode, or its title clearly names the same product.

    Search by name also returns neighbours (a nectar instead of a juice, another flavour
    of the same brand), and shop pages list related goods, so for name matches only the
    page title is trusted: it must contain the brand, the product type (the first word
    of the name) and enough of the other words of the name.
    """
    text = page["text"] or ""
    title = (page.get("title") or text[:300]).casefold()
    title_stems = set(_stems(title))
    wanted_type, page_type = product_type(_stems(name or "")), product_type(_stems(title))
    if wanted_type and page_type and wanted_type != page_type and wanted_type not in {product_type([s]) for s in title_stems}:
        return False  # the barcode alone is not enough: shops list related goods on the page
    name_set = set(_stems(name or ""))
    extra_flavours = [f for f in FLAVOURS if any(stem.startswith(f) for stem in title_stems) and not any(stem.startswith(f) for stem in name_set)]
    if extra_flavours:
        return False
    if barcode and barcode in text:
        return True
    brand_stems = set(_stems(brand or ""))
    # «J7», «J-7» and «J 7» are the same brand in shop titles.
    compact = lambda value: re.sub(r"[^a-zа-яё0-9]", "", value.casefold())
    brand_in_title = not brand or compact(brand) in compact(title) or bool(brand_stems and brand_stems <= title_stems)
    name_stems = [stem for stem in dict.fromkeys(_stems(name or "")) if stem not in brand_stems]
    if not name_stems:
        return bool(brand) and brand_in_title
    matched = [stem for stem in name_stems if stem in title_stems]
    if not brand_in_title:
        # Titles often name the product brand (M&M's) but not the maker (Mars). That is trusted
        # only for long, specific names matched word for word: «Сок яблочный» of another
        # brand must not pass.
        return len(name_stems) >= 3 and len(matched) == len(name_stems)
    # Short names need every word («Сок яблочный» must not match «Сок апельсиновый»);
    # long OFF names often carry a transliterated brand or junk, so half of them is enough.
    required = len(name_stems) if len(name_stems) <= 2 else max(2, (len(name_stems) + 1) // 2)
    return name_stems[0] in title_stems and len(matched) >= required


def search_query(data):
    """Product name and brand find more shop pages than the bare barcode does."""
    name = re.sub(r"[«»\"']", " ", data.name or "").strip()
    brand = (data.brand or "").strip()
    if brand and brand.casefold() not in name.casefold():
        name = f"{brand} {name}"
    name = re.sub(r"\s+", " ", name).strip()[:120]
    if name:
        return f"{name} состав"
    return f"{(data.barcode or '').strip()} состав".strip()


KEYWORDS = re.compile(r"(?i)состав|ингредиент|аллерген|может содержать|пищев|энергетическ|ккал|добавк|\bе\s?-?\d{3}|\be\s?-?\d{3}")


def snippets(text):
    """Short windows around label words, so the model sees the label part of the page only."""
    spans = []
    for match in KEYWORDS.finditer(text):
        start, end = max(0, match.start() - 120), min(len(text), match.end() + 480)
        if spans and start <= spans[-1][1]:
            spans[-1][1] = end
        else:
            spans.append([start, end])
    parts = [re.sub(r"\s+", " ", text[a:b]).strip() for a, b in spans]
    return " … ".join(parts)[:PAGE_TEXT_LIMIT]


# «Состав:», «Состав продукта:», «Состав лапши:» — but not «в составе» inside a sentence.
INGREDIENTS_RE = re.compile(r"(?i)\bсостав\b(?:\s+[а-яё]+){0,2}?\s*[:：\-–—]\s*(.{12,900}?)(?=\s(?:пищевая|энергетическая|условия хранения|срок годности|изготовитель|производитель|хранить|годен|масса нетто|объ[её]м)\b|\n|\"|…|$)")
NUTRITION_RE = re.compile(r"(?i)((?:пищевая|энергетическая)\s+ценность[^\n]{0,300}?\d[\d,.]*\s*(?:ккал|кдж)[^\n]{0,160})")
ADDITIVE_RE = re.compile(r"(?i)\b[еe]\s?-?(\d{3}[a-zа-я]?)\b")


def rule_extract(text):
    """Label fields without AI: the text after «Состав», the nutrition sentence, E-numbers."""
    found = {}
    for match in INGREDIENTS_RE.finditer(text):
        value = clean_ingredients(match.group(1))
        if complete_ingredients(value):
            found["ingredients"] = value
            break
    match = NUTRITION_RE.search(text)
    if match:
        found["nutrition"] = re.sub(r"\s+", " ", match.group(1)).strip(" .;,|")[:300]
    if found.get("ingredients"):
        codes = sorted({f"E{code.upper()}" for code in ADDITIVE_RE.findall(found["ingredients"])})
        if codes:
            found["additives"] = ", ".join(codes)
    return found


def clean_ingredients(value):
    """Cut the list where the marketing text starts: at the first full stop followed by a sentence."""
    value = re.sub(r"\s+", " ", value).strip()
    sentences = re.split(r"(?<![А-ЯA-Z])\.\s+(?=[А-ЯЁA-Z])", value)
    # Keep the trace warning that labels print right after the list; drop what follows.
    kept = [sentences[0]] + [s for s in sentences[1:2] if re.match(r"(?i)(может содержать|содержит|продукт может)", s)]
    return ". ".join(kept).strip(" .;,|")[:900]


def complete_ingredients(value):
    """A cut-off fragment («пшеничная мука в/с») is worse than nothing for allergies."""
    return value.count(",") >= 1 or len(value.split()) >= 4


def as_text(value):
    """Models sometimes answer with a list of ingredients instead of one string."""
    if isinstance(value, list):
        return ", ".join(str(item).strip() for item in value if isinstance(item, (str, int, float)) and str(item).strip())
    return value if isinstance(value, str) else None


ENGLISH_ALLERGENS = {
    "milk": "молоко", "lactose": "лактоза", "gluten": "глютен", "wheat": "пшеница", "barley": "ячмень", "rye": "рожь",
    "oats": "овёс", "eggs": "яйца", "egg": "яйца", "nuts": "орехи", "tree nuts": "орехи", "hazelnuts": "фундук",
    "hazelnut": "фундук", "almonds": "миндаль", "almond": "миндаль", "peanuts": "арахис", "peanut": "арахис",
    "soybeans": "соя", "soybean": "соя", "soya": "соя", "soy": "соя", "fish": "рыба", "crustaceans": "ракообразные",
    "molluscs": "моллюски", "sesame seeds": "кунжут", "sesame": "кунжут", "mustard": "горчица", "celery": "сельдерей",
    "lupin": "люпин", "sulphites": "сульфиты", "sulfites": "сульфиты", "sulphur dioxide and sulphites": "сульфиты",
}


def russian_allergens(value):
    """English allergen names (from an English source page or a tag) are shown in Russian."""
    if not isinstance(value, str):
        return value
    value = re.sub(r"\b[a-z]{2}:", "", value)  # taxonomy prefixes like «en:»
    value = re.sub(r"(?i)\bmay contain traces of\b", "может содержать следы", value)
    value = re.sub(r"(?i)\bmay contain\b", "может содержать", value)
    value = re.sub(r"(?i)\btraces of\b", "следы", value)
    for english in sorted(ENGLISH_ALLERGENS, key=len, reverse=True):
        value = re.sub(rf"(?i)\b{re.escape(english).replace('\\ ', '[ -]')}\b", ENGLISH_ALLERGENS[english], value)
    return value


def allergens_from_ingredients(ingredients):
    low = f" {ingredients.casefold()} "
    groups = [group for group, stems in ALLERGEN_STEMS.items() if any(stem in low for stem in stems)]
    traces = re.search(r"(?i)может содержать[^.;]*", ingredients)
    text = ", ".join(groups)
    if traces:
        text = f"{text}; {traces.group(0).strip()}" if text else traces.group(0).strip()
    return text


def _words(value):
    return [w for w in re.findall(r"[\wё]{3,}", value.casefold()) if not w.isdigit()]


def grounded(field, value, source):
    """The value has to come from the page text, not from the model's memory."""
    if not isinstance(value, str) or not value.strip():
        return False
    low = source.casefold()
    if field == "nutrition":
        numbers = re.findall(r"\d+(?:[.,]\d+)?", value)
        return bool(numbers) and all(number in source for number in numbers)
    if field == "additives":
        codes = re.findall(r"\d{3}", value)
        return bool(codes) and all(code in source for code in codes)
    words = _words(value)
    if not words:
        return False
    hits = sum(1 for word in words if word in low)
    return hits / len(words) >= (0.6 if field == "allergens" else 0.75)


def model_extract(pages, data, fields, api_key):
    """Ask free OpenRouter models in turn; the first readable JSON answer wins."""
    prompt = {
        "product": " ".join(p for p in (data.brand, data.name) if p).strip(),
        "barcode": data.barcode,
        "fields_to_find": fields,
        "pages": [{"url": page["url"], "text": page["snippet"]} for page in pages],
        "rules": "Возьми значения только из текста pages, дословно, и только для этого продукта. ingredients — список ингредиентов после слова «Состав». allergens — только если явно указаны на странице. nutrition — пищевая и энергетическая ценность с числами. additives — пищевые добавки (Е-коды). Неизвестное — null. Ответ — один JSON-объект без пояснений.",
    }
    models = [m.strip() for m in os.getenv("OPENROUTER_FREE_MODELS", DEFAULT_FREE_MODELS).split(",") if m.strip()]
    # Free models think before answering and can spend the whole token budget on it:
    # first ask for short reasoning, then (where the model allows it) for none at all.
    reasoning_modes = ({"effort": "low"}, {"enabled": False})
    for model in models:
        for reasoning in reasoning_modes:
            body = {
                "model": model,
                "messages": [
                    {"role": "system", "content": "Ты извлекаешь данные о продукте из переданного текста страниц. Ничего не добавляй от себя. Ответ — только JSON."},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)[:TOTAL_TEXT_LIMIT + 1500]},
                ],
                "temperature": 0,
                "max_tokens": 1500,
                "reasoning": reasoning,
            }
            try:
                _, payload = _http("https://openrouter.ai/api/v1/chat/completions", data=json.dumps(body).encode(), headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "X-Title": "I-See Food Assistant"}, timeout=25)
                choice = json.loads(payload)["choices"][0]
                content = choice["message"].get("content") or ""
                result = _first_json_object(content)
                if result is not None:
                    return result, model
                print(f"Free model {model} ({reasoning}): answer without JSON (finish_reason={choice.get('finish_reason')}, {len(content)} chars)", flush=True)
            except HTTPError as error:
                print(f"Free model {model} ({reasoning}): HTTP {error.code}", flush=True)
                if error.code in (401, 402, 429):
                    break  # the next reasoning mode will not help with quota or access
            except Exception as error:
                print(f"Free model {model} ({reasoning}): {type(error).__name__}: {error}", flush=True)
                break
    return None, None


def _first_json_object(content):
    content = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", content.strip(), flags=re.IGNORECASE)
    decoder = json.JSONDecoder()
    for start in [m.start() for m in re.finditer(r"\{", content)]:
        try:
            value, _ = decoder.raw_decode(content[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def run_search(query):
    tavily_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not tavily_key:
        return search_duckduckgo(query)
    try:
        return search_tavily(query, tavily_key)
    except SearchUnavailable as error:
        print(f"{error}; trying DuckDuckGo", flush=True)
        return search_duckduckgo(query)


def lookup(data, fields):
    """Find label fields for a product. Returns {field: value, ..., "sources": [...]}."""
    fields = [field for field in fields if field in SUPPORTED_FIELDS]
    if not fields:
        return {"sources": []}
    # Open Food Facts keeps brands as a list («J7, Мултон»); the first one is the trade mark.
    data = SimpleNamespace(barcode=data.barcode, name=data.name, brand=re.split(r"[,;]", data.brand or "")[0].strip())
    barcode = (data.barcode or "").strip()
    queries = [search_query(data)]
    if barcode and not queries[0].startswith(barcode):
        queries.append(f"{barcode} состав")  # used only when the name finds too little
    pages, seen = [], set()
    for query in queries:
        if len(pages) >= 2:
            break
        try:
            results = run_search(query)
        except SearchUnavailable as error:
            if query is queries[0]:
                raise
            print(f"Free search «{query}» skipped: {error}", flush=True)
            break  # keep what the name search already found
        results = [r for r in results if r["url"] not in seen and r["url"].startswith(("http://", "https://")) and not any(h in urlparse(r["url"]).netloc for h in SKIP_HOSTS)][:6]
        seen.update(r["url"] for r in results)
        with ThreadPoolExecutor(max_workers=5) as pool:
            fetched = [page for page in pool.map(fetch_page, results) if page]
        relevant = [page for page in fetched if is_about_product(page, barcode, data.brand, data.name)]
        tavily_key = os.getenv("TAVILY_API_KEY", "").strip()
        unreadable = [page for page in relevant if not snippets(page["text"] or "")]
        if tavily_key and unreadable:
            texts = tavily_extract([page["url"] for page in unreadable], tavily_key)
            for page in unreadable:
                if texts.get(page["url"]):
                    page["text"] = texts[page["url"]]
            print(f"Tavily extract: {sum(1 for p in unreadable if texts.get(p['url']))} of {len(unreadable)} pages read", flush=True)
        for page in relevant:
            page["snippet"] = snippets(page["text"] or "")
            if page["snippet"]:
                pages.append(page)
        print(f"Free search «{query}»: {len(results)} results, {len(pages)} pages about the product", flush=True)
    # Pages that show the exact barcode are the most reliable, so they go first.
    pages.sort(key=lambda page: barcode not in (page["text"] or "") if barcode else False)
    if not pages:
        return {"sources": []}
    source_text = "\n".join(page["snippet"] for page in pages)

    found, used_pages = {}, []
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if api_key:
        result, model = model_extract(pages, data, fields, api_key)
        for field in fields:
            value = as_text((result or {}).get(field))
            if field == "ingredients" and value and not complete_ingredients(value):
                print(f"Free model {model}: ingredients look cut off; dropped", flush=True)
            elif grounded(field, value, source_text):
                found[field] = clean_ingredients(value) if field == "ingredients" else value.strip()[:300]
            elif value:
                print(f"Free model {model}: {field} is not in the page text; dropped", flush=True)
    for page in pages:
        rules = rule_extract(page["snippet"])
        for field in fields:
            if field not in found and rules.get(field):
                found[field] = rules[field]
                used_pages.append(page)
    if "allergens" in fields and "allergens" not in found and found.get("ingredients"):
        derived = allergens_from_ingredients(found["ingredients"])
        if derived:
            found["allergens"] = f"По составу: {derived}"

    def mentions(page):
        low = page["snippet"].casefold()
        return any(_words(value)[:3] and all(w in low for w in _words(value)[:3]) for value in found.values())

    sources = [{"title": page["title"][:180] or urlparse(page["url"]).netloc, "url": page["url"]} for page in pages if page in used_pages or mentions(page)]
    return {**found, "sources": sources[:6]}
