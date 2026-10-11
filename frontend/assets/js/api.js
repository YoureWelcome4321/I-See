(() => {
  const tokenKey = 'ya-vizhu-demo-token-v1';
  const userKey = 'ya-vizhu-demo-user-v1';

  async function request(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
    const token = localStorage.getItem(tokenKey);
    if (token) headers.set('Authorization', `Bearer ${token}`);
    const response = await fetch(path, { ...options, headers });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || 'Не удалось связаться с сервером.');
    return payload;
  }

  window.YaVizhuAPI = {
    request,
    getUser() {
      try { return JSON.parse(localStorage.getItem(userKey) || 'null'); } catch { return null; }
    },
    async login(login, password) {
      const result = await request('/api/login', { method: 'POST', body: JSON.stringify({ login, password }) });
      localStorage.setItem(tokenKey, result.token);
      localStorage.setItem(userKey, JSON.stringify(result.user));
      return result.user;
    },
    logout() {
      localStorage.removeItem(tokenKey);
      localStorage.removeItem(userKey);
    },
    hasToken() { return Boolean(localStorage.getItem(tokenKey)); },
  };
})();
