window.API = {
  async request(method, url, body) {
    const opt = {method, headers: {'Content-Type':'application/json'}};
    if (body !== undefined) opt.body = JSON.stringify(body);
    const res = await fetch(url, opt);
    let data = null;
    try { data = await res.json(); } catch { data = {}; }
    if (!res.ok) {
      const msg = data.detail || '请求失败';
      window.UI?.toast(msg, 'error');
      throw new Error(msg);
    }
    return data;
  },
  get(url){ return this.request('GET', url); },
  post(url, body={}){ return this.request('POST', url, body); },
  put(url, body={}){ return this.request('PUT', url, body); },
  del(url){ return this.request('DELETE', url); }
};
