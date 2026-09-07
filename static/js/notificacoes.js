/*
 * Notificações — comum a todas as páginas logadas.
 *
 * Faz polling de /notificacoes/api/contagem a cada 20s (mesmo
 * intervalo já usado em outras telas do sistema, ex. Central de
 * Visitantes) para popular:
 *   - o badge dentro de cada item do menu lateral (data-modulo)
 *   - o número no sino do topbar
 * e busca a lista detalhada só quando o dropdown é aberto, para não
 * transferir a lista inteira a cada 20s sem necessidade.
 */

const INTERVALO_NOTIF_MS = 20000;
let _dropdownNotifAberto = false;

document.addEventListener("DOMContentLoaded", () => {
  atualizarContagemNotif();
  setInterval(atualizarContagemNotif, INTERVALO_NOTIF_MS);

  document.addEventListener("click", (ev) => {
    const wrap = document.querySelector(".notif-wrap");
    if (_dropdownNotifAberto && wrap && !wrap.contains(ev.target)) {
      fecharDropdownNotif();
    }
  });
});

async function atualizarContagemNotif() {
  const r = await api("get", "/notificacoes/api/contagem");
  if (!r.ok) return;

  const badgeSino = document.getElementById("badge-notif-sino");
  if (badgeSino) {
    if (r.dados.total > 0) {
      badgeSino.textContent = r.dados.total > 99 ? "99+" : r.dados.total;
      badgeSino.style.display = "block";
    } else {
      badgeSino.style.display = "none";
    }
  }

  document.querySelectorAll(".badge-notif-modulo").forEach((el) => {
    const qtd = r.dados.por_modulo[el.dataset.modulo] || 0;
    if (qtd > 0) {
      el.textContent = qtd > 99 ? "99+" : qtd;
      el.style.display = "inline-block";
    } else {
      el.style.display = "none";
    }
  });
}

function alternarDropdownNotif() {
  if (_dropdownNotifAberto) fecharDropdownNotif();
  else abrirDropdownNotif();
}

function abrirDropdownNotif() {
  const dropdown = document.getElementById("notif-dropdown");
  if (!dropdown) return;
  dropdown.classList.add("aberto");
  _dropdownNotifAberto = true;
  carregarListaNotif();
}

function fecharDropdownNotif() {
  const dropdown = document.getElementById("notif-dropdown");
  if (!dropdown) return;
  dropdown.classList.remove("aberto");
  _dropdownNotifAberto = false;
}

async function carregarListaNotif() {
  const caixa = document.getElementById("notif-dropdown-lista");
  if (!caixa) return;

  const r = await api("get", "/notificacoes/api/listar");
  if (!r.ok) {
    caixa.innerHTML = `<div class="notif-vazio">Não foi possível carregar as notificações.</div>`;
    return;
  }
  if (r.dados.length === 0) {
    caixa.innerHTML = `<div class="notif-vazio">Nenhuma notificação pendente.</div>`;
    return;
  }

  caixa.innerHTML = r.dados.map((n) => `
    <button type="button" class="notif-item" onclick="abrirNotificacao(${n.id}, '${(n.url || "").replace(/'/g, "&#39;")}')">
      <div class="notif-item-topo">
        <span class="notif-item-modulo">${_labelModuloNotif(n.modulo)}</span>
        <span class="notif-item-tempo">${_tempoRelativoNotif(n.criado_em)}</span>
      </div>
      <div class="notif-item-titulo">${n.titulo}</div>
      ${n.mensagem ? `<div class="notif-item-mensagem">${n.mensagem}</div>` : ""}
    </button>
  `).join("");
}

async function abrirNotificacao(id, url) {
  await api("post", `/notificacoes/api/${id}/marcar-lida`);
  if (url) {
    window.location.href = url;
  } else {
    atualizarContagemNotif();
    carregarListaNotif();
  }
}

async function marcarTodasNotifLidas() {
  const r = await api("post", "/notificacoes/api/marcar-todas-lidas");
  if (r.ok) {
    atualizarContagemNotif();
    carregarListaNotif();
  }
}

const _LABELS_MODULO_NOTIF = {
  saidas: "Saídas", visitantes: "Visitantes", chamados: "Chamados",
  chaves: "Chaves", ocorrencias: "Ocorrências", evasao: "Evasão",
  biblioteca: "Biblioteca", agendamento: "Agendamento", sinal: "Sinal",
  iot: "IoT", pontualidade: "Pontualidade", alunos: "Alunos",
  monitoramento: "Monitoramento", admin: "Admin",
};

function _labelModuloNotif(id) {
  return _LABELS_MODULO_NOTIF[id] || id;
}

function _tempoRelativoNotif(isoString) {
  const diffMs = Date.now() - new Date(isoString).getTime();
  const min = Math.floor(diffMs / 60000);
  if (min < 1) return "agora";
  if (min < 60) return `há ${min} min`;
  const h = Math.floor(min / 60);
  if (h < 24) return `há ${h}h`;
  const d = Math.floor(h / 24);
  return `há ${d}d`;
}
