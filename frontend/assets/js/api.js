(() => {
  const savedFontSize = localStorage.getItem('ya-vizhu-font-size');
  if (savedFontSize) document.documentElement.dataset.fontSize = savedFontSize;
  const tokenKey = 'ya-vizhu-demo-token-v1';
  const userKey = 'ya-vizhu-demo-user-v1';

  async function request(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
    const token = localStorage.getItem(tokenKey);
    if (token) headers.set('Authorization', `Bearer ${token}`);
    const response = await fetch(path, { ...options, headers });
    const payload = await response.json().catch(() => ({}));
    if (response.status === 401 && token) {
      // The session expired or was revoked: drop the stale token so the UI offers a login.
      localStorage.removeItem(tokenKey);
      localStorage.removeItem(userKey);
    }
    if (!response.ok) throw new Error(payload.detail || payload.error || 'Не удалось связаться с сервером.');
    return payload;
  }

  window.YaVizhuAPI = {
    request,
    getUser() {
      try { return JSON.parse(localStorage.getItem(userKey) || 'null'); } catch { return null; }
    },
    async register(name, phone, password, restrictions) {
      const result = await request('/api/register', {
        method: 'POST',
        body: JSON.stringify({ name, phone, password, restrictions }),
      });
      localStorage.setItem(tokenKey, result.token);
      localStorage.setItem(userKey, JSON.stringify(result.user));
      return result.user;
    },
    async checkPhone(phone) {
      return request(`/api/register/check?phone=${encodeURIComponent(phone)}`);
    },
    async login(login, password) {
      const result = await request('/api/login', { method: 'POST', body: JSON.stringify({ login, password }) });
      localStorage.setItem(tokenKey, result.token);
      localStorage.setItem(userKey, JSON.stringify(result.user));
      return result.user;
    },
    logout() {
      if (localStorage.getItem(tokenKey)) request('/api/logout', { method: 'POST' }).catch(() => {});
      localStorage.removeItem(tokenKey);
      localStorage.removeItem(userKey);
    },
    hasToken() { return Boolean(localStorage.getItem(tokenKey)); },
  };
})();
