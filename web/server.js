// Web panel tạo + quản lý VPS — Node.js (Express).
// Phục vụ giao diện ở port 9999 và proxy xuống FastAPI Proxmox API.
// API key chỉ nằm ở đây (server-side), trình duyệt không thấy.
//
// Bổ sung: Shell Console (xterm.js serial) — Node làm cầu WebSocket tới Proxmox.
// Trình duyệt KHÔNG nói trực tiếp với Proxmox: nó nối WS tới Node, Node mở WS
// ngược lên Proxmox và chèn cookie phiên (PVEAuthCookie) ở handshake — vì trình
// duyệt không set được header trên WebSocket, và websocket Proxmox không nhận API token.

import express from 'express';
import session from 'express-session';
import dotenv from 'dotenv';
import http from 'node:http';
import crypto from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { WebSocketServer, WebSocket } from 'ws';

dotenv.config();

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.PORT) || 9999;
const API_URL = (process.env.PROXMOX_API_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
const API_KEY = process.env.API_KEY || '';
// Host Proxmox để mở WebSocket console. Mặc định 127.0.0.1:8006 — tới được nhờ
// SSH tunnel forward thêm cổng 8006 (xem README/docs). Đổi sang IP công khai nếu chạy khác.
const PROXMOX_WS_URL = (process.env.PROXMOX_WS_URL || 'https://127.0.0.1:8006').replace(/\/$/, '');

// ---- Đăng nhập web panel ----
const PANEL_USER = process.env.PANEL_USER || '';
const PANEL_PASS_HASH = process.env.PANEL_PASS_HASH || ''; // dạng "salt:scryptHex"
const SESSION_SECRET = process.env.SESSION_SECRET || crypto.randomBytes(32).toString('hex');

function checkPassword(input) {
  if (!PANEL_PASS_HASH) return false;
  const [salt, hash] = PANEL_PASS_HASH.split(':');
  if (!salt || !hash) return false;
  const stored = Buffer.from(hash, 'hex');
  const test = crypto.scryptSync(String(input), salt, stored.length);
  return test.length === stored.length && crypto.timingSafeEqual(test, stored);
}

const loginPage = (err) => `<!DOCTYPE html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Đăng nhập</title>
<style>body{font-family:system-ui,-apple-system,sans-serif;background:#0f172a;color:#e2e8f0;display:grid;place-items:center;height:100vh;margin:0}
form{background:#1e293b;border:1px solid #334155;border-radius:12px;padding:28px;width:320px}
h1{font-size:18px;margin:0 0 18px}input{width:100%;box-sizing:border-box;background:#0b1220;border:1px solid #334155;color:#e2e8f0;border-radius:8px;padding:11px 12px;margin-bottom:12px;font-size:14px}
button{width:100%;background:#3b82f6;color:#fff;border:0;border-radius:8px;padding:12px;font-weight:600;cursor:pointer;font-size:14px}
.err{color:#ef4444;font-size:13px;margin-bottom:12px}</style></head>
<body><form method="post" action="/login">
<h1>🔐 Proxmox VPS Panel</h1>
${err ? '<div class="err">Sai tài khoản hoặc mật khẩu.</div>' : ''}
<input name="username" placeholder="User" autofocus autocomplete="username">
<input name="password" type="password" placeholder="Mật khẩu" autocomplete="current-password">
<button type="submit">Đăng nhập</button></form></body></html>`;

// ---- Presets: NGUỒN SỰ THẬT DUY NHẤT cho cấu hình cho phép ----
const PRESETS = {
  cpu: [4, 8, 16], // số vCPU
  ramGb: [4, 8, 16, 24, 32, 64], // RAM (GB)
  ssdGb: [100, 200, 300], // SSD (GB)
};

const app = express();
app.use(express.json());
app.use(express.urlencoded({ extended: false }));
app.use(
  session({
    secret: SESSION_SECRET,
    resave: false,
    saveUninitialized: false,
    cookie: { httpOnly: true, sameSite: 'lax', maxAge: 8 * 3600 * 1000 },
  })
);

// Trang đăng nhập (public)
app.get('/login', (req, res) => {
  if (req.session?.authed) return res.redirect('/');
  res.type('html').send(loginPage(req.query.err));
});
app.post('/login', (req, res) => {
  const { username, password } = req.body || {};
  if (username === PANEL_USER && checkPassword(password || '')) {
    req.session.authed = true;
    req.session.user = username;
    return res.redirect('/');
  }
  res.redirect('/login?err=1');
});
app.post('/logout', (req, res) => {
  req.session.destroy(() => res.redirect('/login'));
});

// Cổng chặn: mọi thứ còn lại cần đăng nhập
app.use((req, res, next) => {
  if (req.session?.authed) return next();
  if (req.path.startsWith('/api/')) return res.status(401).json({ detail: 'Chưa đăng nhập.' });
  return res.redirect('/login');
});

// Tĩnh + API: từ đây trở đi đã qua cổng chặn
app.use(express.static(path.join(__dirname, 'public')));

// Bắt lỗi async gọn gàng
const wrap = (fn) => (req, res) =>
  fn(req, res).catch((err) => {
    console.error(err);
    res.status(502).json({ detail: `Không gọi được Proxmox API: ${err.message}` });
  });

// Gọi xuống FastAPI
async function callApi(pathname, { method = 'GET', body } = {}) {
  const res = await fetch(`${API_URL}${pathname}`, {
    method,
    headers: { 'Content-Type': 'application/json', 'X-API-Key': API_KEY },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  return { ok: res.ok, status: res.status, data };
}

// Trả presets để frontend dựng dropdown
app.get('/api/options', (_req, res) => res.json(PRESETS));

// Liệt kê VPS
app.get(
  '/api/vps',
  wrap(async (_req, res) => {
    const r = await callApi('/api/v1/vps');
    res.status(r.status).json(r.data);
  })
);

// Chi tiết một VPS (config + status) để hiển thị trực quan
app.get(
  '/api/vps/:vmid',
  wrap(async (req, res) => {
    const r = await callApi(`/api/v1/vps/${req.params.vmid}/detail`);
    res.status(r.status).json(r.data);
  })
);

// Tạo VPS từ lựa chọn preset
app.post(
  '/api/vps',
  wrap(async (req, res) => {
    const { name, cpu, ramGb, ssdGb, ciUser, ciPassword } = req.body || {};

    const errors = [];
    if (!name || !/^[a-zA-Z0-9-]+$/.test(name)) {
      errors.push('name chỉ gồm chữ, số, dấu "-" và không được rỗng');
    }
    if (!PRESETS.cpu.includes(Number(cpu))) errors.push(`CPU phải thuộc {${PRESETS.cpu.join(', ')}}`);
    if (!PRESETS.ramGb.includes(Number(ramGb))) errors.push(`RAM phải thuộc {${PRESETS.ramGb.join(', ')}} GB`);
    if (!PRESETS.ssdGb.includes(Number(ssdGb))) errors.push(`SSD phải thuộc {${PRESETS.ssdGb.join(', ')}} GB`);
    if (errors.length) return res.status(400).json({ detail: errors.join('; ') });

    // Map preset -> payload FastAPI. Network để TRỐNG = DHCP (thiết kế sau).
    const payload = {
      name,
      cores: Number(cpu),
      memory_mb: Number(ramGb) * 1024,
      disk_gb: Number(ssdGb),
    };
    if (ciUser) payload.ci_user = ciUser;
    if (ciPassword) payload.ci_password = ciPassword;

    const r = await callApi('/api/v1/vps', { method: 'POST', body: payload });
    res.status(r.status).json(r.data);
  })
);

// Xoá VPS
app.delete(
  '/api/vps/:vmid',
  wrap(async (req, res) => {
    const r = await callApi(`/api/v1/vps/${req.params.vmid}`, { method: 'DELETE' });
    if (r.status === 204) return res.status(204).end();
    res.status(r.status).json(r.data);
  })
);

// ---- Shell Console ----
// Phiên console tạm thời: token -> {node, vmid, port, ticket, cookie}. Dùng 1 lần, TTL ngắn.
const consoleSessions = new Map();
const CONSOLE_TTL_MS = 60_000;

function sweepConsoleSessions() {
  const now = Date.now();
  for (const [k, v] of consoleSessions) if (v.expires < now) consoleSessions.delete(k);
}

// Lấy ticket mở console: gọi FastAPI, cất cookie phía server, trả wsToken + user + ticket cho client.
app.post(
  '/api/vps/:vmid/console',
  wrap(async (req, res) => {
    const r = await callApi(`/api/v1/vps/${req.params.vmid}/console`, { method: 'POST' });
    if (!r.ok) return res.status(r.status).json(r.data);
    const { node, vmid, port, ticket, user, auth_header } = r.data || {};
    if (!ticket || !auth_header || !port) {
      return res.status(502).json({ detail: 'FastAPI không trả về ticket console hợp lệ.' });
    }
    sweepConsoleSessions();
    const token = crypto.randomBytes(18).toString('hex');
    // auth_header (PVEAPIToken) GIỮ phía server, không gửi ra trình duyệt.
    consoleSessions.set(token, { node, vmid, port, ticket, authHeader: auth_header, expires: Date.now() + CONSOLE_TTL_MS });
    // Trình duyệt cần user + ticket cho thông điệp xác thực đầu tiên của giao thức xterm.
    res.json({ wsToken: token, user, ticket, node, vmid, port });
  })
);

// ---- HTTP server + WebSocket bridge ----
const server = http.createServer(app);
const wss = new WebSocketServer({ noServer: true });

server.on('upgrade', (req, socket, head) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  if (url.pathname !== '/api/console') {
    socket.destroy();
    return;
  }
  const token = url.searchParams.get('token');
  const sess = token && consoleSessions.get(token);
  if (!sess || sess.expires < Date.now()) {
    socket.destroy();
    return;
  }
  consoleSessions.delete(token); // dùng 1 lần
  wss.handleUpgrade(req, socket, head, (clientWs) => bridgeConsole(clientWs, sess));
});

// Cầu nối: trình duyệt <-> Proxmox vncwebsocket. Node chèn cookie ở handshake upstream.
function bridgeConsole(clientWs, sess) {
  const wsBase = PROXMOX_WS_URL.replace(/^http/, 'ws');
  const upstreamUrl =
    `${wsBase}/api2/json/nodes/${sess.node}/qemu/${sess.vmid}/vncwebsocket` +
    `?port=${sess.port}&vncticket=${encodeURIComponent(sess.ticket)}`;

  const upstream = new WebSocket(upstreamUrl, [], {
    headers: { Authorization: sess.authHeader },
    rejectUnauthorized: false, // Proxmox self-signed
  });

  let upstreamOpen = false;
  const pending = [];

  clientWs.on('message', (data, isBinary) => {
    if (upstreamOpen) upstream.send(data, { binary: isBinary });
    else pending.push([data, isBinary]); // gồm cả thông điệp auth "user:ticket\n" đầu tiên
  });

  upstream.on('open', () => {
    upstreamOpen = true;
    for (const [d, b] of pending) upstream.send(d, { binary: b });
    pending.length = 0;
  });

  upstream.on('message', (data, isBinary) => {
    if (clientWs.readyState === WebSocket.OPEN) clientWs.send(data, { binary: isBinary });
  });

  const closeBoth = () => {
    try { clientWs.close(); } catch { /* ignore */ }
    try { upstream.close(); } catch { /* ignore */ }
  };
  clientWs.on('close', closeBoth);
  clientWs.on('error', closeBoth);
  upstream.on('close', closeBoth);
  upstream.on('error', (e) => {
    console.error('Console upstream WS error:', e.message);
    try {
      if (clientWs.readyState === WebSocket.OPEN) {
        clientWs.send(`\r\n[Lỗi kết nối console tới Proxmox: ${e.message}]\r\n`);
      }
    } catch { /* ignore */ }
    closeBoth();
  });
}

server.listen(PORT, () => {
  console.log(`Proxmox VPS web panel chạy tại http://localhost:${PORT}`);
  console.log(`Proxy tới FastAPI: ${API_URL}`);
  console.log(`Console WS tới Proxmox: ${PROXMOX_WS_URL}`);
});
