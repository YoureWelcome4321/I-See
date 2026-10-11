function initStoreFinder() {
  const mapElement = document.querySelector("#stores-map");
  const listElement = document.querySelector("#stores-list");
  const statusElement = document.querySelector("#stores-status");
  const countElement = document.querySelector("#stores-count");
  const refreshButton = document.querySelector("#refresh-stores");
  if (!mapElement || !listElement || !statusElement || !countElement || !refreshButton) return;

  const map = L.map(mapElement, { scrollWheelZoom: false, zoomControl: false }).setView([0, 0], 2);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(map);
  L.control.zoom({ position: "bottomright" }).addTo(map);
  const markers = L.featureGroup().addTo(map);
  let userMarker = null;
  let lastPosition = null;
  let requestId = 0;

  const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
  const distanceBetween = (a, b) => {
    const radians = (degrees) => degrees * Math.PI / 180;
    const dLat = radians(b.lat - a.lat);
    const dLon = radians(b.lon - a.lon);
    const arc = Math.sin(dLat / 2) ** 2 + Math.cos(radians(a.lat)) * Math.cos(radians(b.lat)) * Math.sin(dLon / 2) ** 2;
    return 6371000 * 2 * Math.atan2(Math.sqrt(arc), Math.sqrt(1 - arc));
  };
  const formatDistance = (meters) => meters < 1000 ? `${Math.round(meters / 10) * 10} м` : `${(meters / 1000).toFixed(1).replace(".", ",")} км`;
  const russianCount = (count, one, few, many) => {
    const remainder10 = count % 10;
    const remainder100 = count % 100;
    if (remainder10 === 1 && remainder100 !== 11) return one;
    if (remainder10 >= 2 && remainder10 <= 4 && (remainder100 < 12 || remainder100 > 14)) return few;
    return many;
  };
  const getAddress = (tags) => {
    const street = tags["addr:street"];
    const house = tags["addr:housenumber"];
    const city = tags["addr:city"];
    return [street && [street, house].filter(Boolean).join(", "), city].filter(Boolean).join(" · ") || "Адрес не указан на карте";
  };
  const getCategory = (tags) => {
    if (tags.shop === "supermarket" || tags.shop === "department_store") return "Супермаркет";
    if (tags.shop === "convenience") return "Магазин у дома";
    if (tags.shop === "greengrocer") return "Овощи и фрукты";
    if (tags.shop === "bakery") return "Пекарня";
    return "Продуктовый магазин";
  };
  const getPoint = (element) => element.type === "node"
    ? { lat: element.lat, lon: element.lon }
    : element.center && { lat: element.center.lat, lon: element.center.lon };

  function showEmpty(message) {
    listElement.innerHTML = `<div class="stores-empty"><span class="stores-empty-icon" aria-hidden="true">⌖</span><p>${escapeHtml(message)}</p></div>`;
    countElement.textContent = "0";
  }

  function renderStores(elements, origin) {
    const unique = new Map();
    for (const element of elements) {
      const tags = element.tags || {};
      const point = getPoint(element);
      if (!point || !tags.name) continue;
      const store = {
        id: `${element.type}-${element.id}`,
        name: tags.name,
        tags,
        ...point,
        category: getCategory(tags),
        address: getAddress(tags),
      };
      store.distance = distanceBetween(origin, store);
      unique.set(store.id, store);
    }
    const stores = [...unique.values()].sort((a, b) => a.distance - b.distance);
    markers.clearLayers();
    if (!stores.length) {
      showEmpty("В этом радиусе магазины не найдены. Попробуйте увеличить расстояние поиска.");
      return stores;
    }
    countElement.textContent = stores.length > 99 ? "99+" : String(stores.length);
    listElement.innerHTML = stores.map((store, index) => `
      <article class="store-item" data-store-id="${escapeHtml(store.id)}" tabindex="0">
        <span class="store-number" aria-hidden="true">${index + 1}</span>
        <div class="store-item-main"><h3>${escapeHtml(store.name)}</h3><p class="store-category">${escapeHtml(store.category)}</p><p class="store-address">${escapeHtml(store.address)}</p></div>
        <div class="store-item-meta"><strong>${formatDistance(store.distance)}</strong><a href="https://www.openstreetmap.org/directions?engine=fossgis_osrm_car&route=${origin.lat}%2C${origin.lon}%3B${store.lat}%2C${store.lon}" target="_blank" rel="noopener noreferrer" aria-label="Маршрут до ${escapeHtml(store.name)}">Маршрут ↗</a></div>
      </article>`).join("");

    stores.forEach((store, index) => {
      const marker = L.marker([store.lat, store.lon], {
        icon: L.divIcon({ className: "store-map-marker-wrap", html: `<span class="store-map-marker"><span>${index + 1}</span></span>`, iconSize: [34, 34], iconAnchor: [17, 17] }),
      }).bindPopup(`<strong>${escapeHtml(store.name)}</strong><br>${escapeHtml(formatDistance(store.distance))}`).addTo(markers);
      store.marker = marker;
    });
    listElement.querySelectorAll(".store-item").forEach((item) => {
      const activate = () => {
        const store = stores.find((candidate) => candidate.id === item.dataset.storeId);
        if (!store) return;
        map.flyTo([store.lat, store.lon], 16, { duration: 0.45 });
        store.marker.openPopup();
        listElement.querySelectorAll(".store-item").forEach((node) => node.classList.toggle("is-active", node === item));
      };
      item.addEventListener("click", activate);
      item.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") { event.preventDefault(); activate(); }
      });
    });
    return stores;
  }

  async function loadStores(origin, id) {
    const radius = 2000;
    const cacheKey = `stores-osm-${origin.lat.toFixed(3)}-${origin.lon.toFixed(3)}-${radius}`;
    let cached = null;
    try {
      cached = JSON.parse(sessionStorage.getItem(cacheKey) || "null");
    } catch {
      cached = null;
    }
    if (cached?.elements?.length) {
      renderStores(cached.elements, origin);
      statusElement.textContent = "Показали сохранённые магазины. Проверяем актуальные данные…";
    }
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 42000);
    try {
      const response = await fetch(`/api/stores?lat=${encodeURIComponent(origin.lat)}&lon=${encodeURIComponent(origin.lon)}`, {
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`Backend HTTP ${response.status}`);
      const data = await response.json();
      if (!Array.isArray(data.elements) || data.remark) throw new Error(data.remark || "Invalid store response");
      if (id !== requestId) return;
      const elements = data.elements;
      try {
        sessionStorage.setItem(cacheKey, JSON.stringify({ at: Date.now(), elements }));
      } catch {
        // Session storage is optional; the live result still works.
      }
      const stores = renderStores(elements, origin);
      statusElement.textContent = stores.length
        ? `Нашли ${stores.length} ${russianCount(stores.length, "магазин", "магазина", "магазинов")} в радиусе ${radius / 1000} км. Ближайшие — в начале списка.`
        : `В радиусе ${radius / 1000} км магазины не найдены.`;
    } catch (error) {
      if (id !== requestId) return;
      if (cached?.elements?.length) {
        const ageMinutes = Math.max(1, Math.round((Date.now() - cached.at) / 60000));
        statusElement.textContent = `Сервис временно недоступен. Показаны сохранённые магазины (${ageMinutes} мин. назад).`;
        return;
      }
      statusElement.textContent = "Не удалось загрузить магазины. Проверьте подключение к интернету и попробуйте ещё раз.";
      showEmpty("Сервис магазинов временно не отвечает. Попробуйте обновить список чуть позже.");
    } finally {
      window.clearTimeout(timeout);
    }
  }

  function findStores() {
    if (!navigator.geolocation) {
      statusElement.textContent = "Этот браузер не поддерживает определение местоположения.";
      return;
    }
    const id = ++requestId;
    statusElement.textContent = "Запрашиваем доступ к вашему местоположению…";
    navigator.geolocation.getCurrentPosition(async (position) => {
      if (id !== requestId) return;
      lastPosition = { lat: position.coords.latitude, lon: position.coords.longitude };
      mapElement.classList.add("has-location");
      if (userMarker) userMarker.remove();
      userMarker = L.circleMarker([lastPosition.lat, lastPosition.lon], {
        radius: 9, color: "#fff", weight: 3, fillColor: "#287f3b", fillOpacity: 1,
      }).bindPopup("Вы здесь").addTo(map);
      map.setView([lastPosition.lat, lastPosition.lon], 15);
      map.invalidateSize();
      statusElement.textContent = "Ищем магазины в радиусе 2 км…";
      refreshButton.disabled = true;
      try {
        await loadStores(lastPosition, id);
      } finally {
        if (id === requestId) refreshButton.disabled = false;
      }
    }, (error) => {
      if (id !== requestId) return;
      const message = error.code === error.PERMISSION_DENIED
        ? "Доступ к местоположению запрещён. Разрешите его в настройках браузера и повторите поиск."
        : error.code === error.TIMEOUT
          ? "Не удалось определить местоположение вовремя. Попробуйте ещё раз."
          : "Не получилось определить местоположение. Проверьте настройки геолокации.";
      statusElement.textContent = message;
    }, { enableHighAccuracy: false, timeout: 25000, maximumAge: 300000 });
  }

  async function refreshStores() {
    if (!lastPosition) {
      findStores();
      return;
    }
    const id = ++requestId;
    refreshButton.disabled = true;
    statusElement.textContent = "Обновляем список магазинов в радиусе 2 км…";
    try {
      await loadStores(lastPosition, id);
    } finally {
      if (id === requestId) refreshButton.disabled = false;
    }
  }

  refreshButton.addEventListener("click", refreshStores);
  window.addEventListener("resize", () => map.invalidateSize());
  findStores();
}

document.addEventListener("DOMContentLoaded", initStoreFinder);
