// Frontend logic: dựng dropdown từ presets của server, tạo & liệt kê VPS.

const $ = (id) => document.getElementById(id);

const TEMPLATE_VMID = 9000; // template clone — ẩn khỏi danh sách thao tác

// ---- Dựng dropdown từ /api/options ----
async function loadOptions() {
  const presets = await fetch('/api/options').then((r) => r.json());
  fill('cpu', presets.cpu, (v) => `${v} vCPU`);
  fill('ramGb', presets.ramGb, (v) => `${v} GB`);
  fill('ssdGb', presets.ssdGb, (v) => `${v} GB`);
}

function fill(id, values, label) {
  const sel = $(id);
  sel.innerHTML = values.map((v) => `<option value="${v}">${label(v)}</option>`).join('');
}

// ---- Hiển thị kết quả ----
function showResult(message, ok) {
  const el = $('result');
  el.textContent = message;
  el.className = `result ${ok ? 'ok' : 'err'}`;
  el.hidden = false;
}

const esc = (s) =>
  String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

// Hiện thông tin VPS vừa tạo + USER/PASS riêng của nó (để giao cho khách)
function showCreds(data, user, pass) {
  const el = $('result');
  el.className = 'result ok';
  el.hidden = false;
  el.innerHTML = `✅ Đã tạo VPS "<b>${esc(data.name)}</b>" — VMID <b>${esc(data.vmid)}</b> (${esc(data.status)}).
    <div class="creds">
      <div>👤 User: <code>${esc(user || '—')}</code></div>
      <div>🔑 Pass: <code>${esc(pass || '—')}</code></div>
      <div class="muted" style="text-align:left">Lưu lại — đây là tài khoản <b>toàn quyền (sudo)</b> của riêng VPS này, độc lập với Proxmox. Mở <b>⌨ Console</b> để đăng nhập.</div>
    </div>`;
}

// Sinh mật khẩu ngẫu nhiên mạnh (tránh ký tự dễ nhầm)
function genPassword(len = 16) {
  const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789';
  const arr = new Uint32Array(len);
  crypto.getRandomValues(arr);
  return Array.from(arr, (n) => chars[n % chars.length]).join('');
}
$('gen-pw').addEventListener('click', () => {
  $('ciPassword').value = genPassword();
});

// ---- Tạo VPS ----
$('create-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const btn = $('submit-btn');
  btn.disabled = true;
  btn.textContent = 'Đang tạo…';
  $('result').hidden = true;

  const ciUser = $('ciUser').value.trim();
  const ciPassword = $('ciPassword').value;
  const body = {
    name: $('name').value.trim(),
    cpu: Number($('cpu').value),
    ramGb: Number($('ramGb').value),
    ssdGb: Number($('ssdGb').value),
    ciUser: ciUser || undefined,
    ciPassword: ciPassword || undefined,
  };

  try {
    const res = await fetch('/api/vps', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (res.ok) {
      showCreds(data, ciUser, ciPassword);
      $('name').value = '';
      $('ciPassword').value = '';
      await loadVps();
    } else {
      showResult(`❌ Lỗi (${res.status}): ${data.detail || JSON.stringify(data)}`, false);
    }
  } catch (err) {
    showResult(`❌ Không gọi được server: ${err.message}`, false);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Tạo VPS';
  }
});

// ---- Liệt kê VPS ----
async function loadVps() {
  const tbody = $('vps-tbody');
  try {
    const res = await fetch('/api/vps');
    const list = await res.json();
    if (!Array.isArray(list)) {
      tbody.innerHTML = `<tr><td colspan="7" class="muted">Lỗi: ${list.detail || 'không tải được'}</td></tr>`;
      return;
    }
    if (list.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" class="muted">Chưa có VM nào.</td></tr>`;
      return;
    }
    tbody.innerHTML = list
      .map((vm) => {
        const isTemplate = vm.vmid === TEMPLATE_VMID;
        const ram = vm.memory_mb ? `${Math.round(vm.memory_mb / 1024)} GB` : '—';
        const badge = `<span class="badge ${vm.status === 'running' ? 'running' : 'stopped'}">${vm.status}</span>`;
        const name = (vm.name || '').replace(/"/g, '&quot;');
        const action = isTemplate
          ? '<span class="muted">template</span>'
          : `<div class="actions">
               <button class="ghost" data-act="detail" data-vmid="${vm.vmid}">ℹ︎ Chi tiết</button>
               <button class="ghost" data-act="console" data-vmid="${vm.vmid}" data-name="${name}">⌨ Console</button>
               <button class="danger" data-act="delete" data-vmid="${vm.vmid}" data-name="${name}">Xoá</button>
             </div>`;
        return `<tr data-row="${vm.vmid}">
          <td>${vm.vmid}</td>
          <td>${vm.name || '—'}</td>
          <td>${vm.node}</td>
          <td>${badge}</td>
          <td>${vm.cores ?? '—'}</td>
          <td>${ram}</td>
          <td>${action}</td>
        </tr>`;
      })
      .join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" class="muted">Không tải được: ${err.message}</td></tr>`;
  }
}

// ---- Thao tác per-VM (event delegation): chi tiết / console / xoá ----
$('vps-tbody').addEventListener('click', (e) => {
  const btn = e.target.closest('button[data-act]');
  if (!btn) return;
  const { act, vmid, name } = btn.dataset;
  if (act === 'console') return openConsole(vmid, name);
  if (act === 'detail') return toggleDetail(vmid, btn);
  if (act === 'delete') return deleteVps(vmid, name, btn);
});

// Mở Shell Console (tab mới) — console.html tự lấy ticket + nối WebSocket
function openConsole(vmid, name) {
  const q = new URLSearchParams({ vmid, name: name || '' });
  window.open(`/console.html?${q.toString()}`, `console-${vmid}`, 'width=900,height=560');
}

// Bật/tắt hàng chi tiết cấu hình VM
async function toggleDetail(vmid, btn) {
  const existing = document.querySelector(`tr[data-detail="${vmid}"]`);
  if (existing) {
    existing.remove();
    return;
  }
  const row = document.querySelector(`tr[data-row="${vmid}"]`);
  if (!row) return;
  const tr = document.createElement('tr');
  tr.setAttribute('data-detail', vmid);
  tr.innerHTML = `<td colspan="7" class="muted">Đang tải chi tiết…</td>`;
  row.after(tr);
  try {
    const res = await fetch(`/api/vps/${vmid}`);
    const d = await res.json();
    if (!res.ok) throw new Error(d.detail || `HTTP ${res.status}`);
    const ram = d.memory_mb ? `${Math.round(d.memory_mb / 1024)} GB (${d.memory_mb} MB)` : '—';
    const disk = d.disk_gb ? `${d.disk_gb} GB` : '—';
    const up = d.uptime ? fmtUptime(d.uptime) : '—';
    tr.innerHTML = `<td colspan="7">
      <div class="detail-grid">
        <div><span class="k">Disk</span>${disk}</div>
        <div><span class="k">RAM</span>${ram}</div>
        <div><span class="k">CPU</span>${d.cores ?? '—'} vCPU</div>
        <div><span class="k">IP (cloud-init)</span>${d.ip_config || '—'}</div>
        <div><span class="k">Bridge</span>${d.bridge || '—'}</div>
        <div><span class="k">OS type</span>${d.ostype || '—'}</div>
        <div><span class="k">Uptime</span>${up}</div>
        <div><span class="k">Node</span>${d.node}</div>
      </div>
    </td>`;
  } catch (err) {
    tr.innerHTML = `<td colspan="7" class="muted">Không tải được chi tiết: ${err.message}</td>`;
  }
}

function fmtUptime(s) {
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  return [d && `${d}d`, h && `${h}h`, `${m}m`].filter(Boolean).join(' ');
}

// Xoá VPS
async function deleteVps(vmid, name, btn) {
  if (!confirm(`Xoá VPS ${name || vmid} (VMID ${vmid})? Không hoàn tác được.`)) return;
  btn.disabled = true;
  btn.textContent = 'Đang xoá…';
  try {
    const res = await fetch(`/api/vps/${vmid}`, { method: 'DELETE' });
    if (res.status === 204) {
      showResult(`🗑️ Đã xoá VMID ${vmid}.`, true);
      await loadVps();
    } else {
      const data = await res.json().catch(() => ({}));
      showResult(`❌ Xoá lỗi (${res.status}): ${data.detail || ''}`, false);
      btn.disabled = false;
      btn.textContent = 'Xoá';
    }
  } catch (err) {
    showResult(`❌ Không gọi được server: ${err.message}`, false);
    btn.disabled = false;
    btn.textContent = 'Xoá';
  }
}

$('refresh-btn').addEventListener('click', loadVps);

// ---- Khởi tạo ----
loadOptions().then(loadVps);
