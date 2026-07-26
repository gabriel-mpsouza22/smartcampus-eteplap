




async function api(metodo, url, corpo = null) {
  const opcoes = {
    method: metodo,
    headers: { "Content-Type": "application/json" },
  };
  if (corpo) opcoes.body = JSON.stringify(corpo);

  try {
    const resposta = await fetch(url, opcoes);
    const dados = await resposta.json();
    if (!resposta.ok) {
      return { ok: false, erro: dados.erro || `Erro ${resposta.status}` };
    }
    return { ok: true, dados };
  } catch (e) {
    return { ok: false, erro: "Erro de conexão com o servidor." };
  }
}




function mostrarAlerta(mensagem, tipo = "info", duracaoMs = 4000) {
  let el = document.getElementById("alerta-global");
  if (!el) {
    el = document.createElement("div");
    el.id = "alerta-global";
    el.style.cssText = "position:fixed;top:72px;right:24px;z-index:9999;max-width:380px;";
    document.body.appendChild(el);
  }

  const icones = { erro: "✗", sucesso: "✓", aviso: "⚠", info: "ℹ" };
  el.innerHTML = `
    <div class="alerta alerta-${tipo}" role="alert" style="animation:fadeIn 0.2s ease;">
      <span>${icones[tipo] || "ℹ"}</span>
      <span>${mensagem}</span>
    </div>`;

  if (duracaoMs > 0) {
    setTimeout(() => { el.innerHTML = ""; }, duracaoMs);
  }
}



function mostrarSpinner(idBotao) {
  const btn = document.getElementById(idBotao);
  if (!btn) return;
  btn._textoOriginal = btn.innerHTML;
  btn.innerHTML = '<span class="spinner"></span>';
  btn.disabled = true;
}

function ocultarSpinner(idBotao) {
  const btn = document.getElementById(idBotao);
  if (!btn || !btn._textoOriginal) return;
  btn.innerHTML = btn._textoOriginal;
  btn.disabled = false;
}



function confirmar(mensagem) {
  return window.confirm(mensagem);
}



function inicializarSidebarMobile() {
  const btnMenu = document.getElementById("btn-menu-mobile");
  const sidebar = document.querySelector(".sidebar");
  if (!btnMenu || !sidebar) return;

  btnMenu.addEventListener("click", () => {
    sidebar.classList.toggle("aberta");
  });

  
  document.addEventListener("click", (e) => {
    if (!sidebar.contains(e.target) && !btnMenu.contains(e.target)) {
      sidebar.classList.remove("aberta");
    }
  });
}



function marcarLinkAtivo() {
  const atual = window.location.pathname;
  document.querySelectorAll(".sidebar-nav a").forEach((link) => {
    const href = link.getAttribute("href");
    if (href && atual.startsWith(href) && href !== "/") {
      link.classList.add("ativo");
    }
  });
}



function inicializarRelogio(idElemento) {
  const el = document.getElementById(idElemento);
  if (!el) return;

  function atualizar() {
    const agora = new Date();
    const h = String(agora.getHours()).padStart(2, "0");
    const m = String(agora.getMinutes()).padStart(2, "0");
    const s = String(agora.getSeconds()).padStart(2, "0");
    el.textContent = `${h}:${m}:${s}`;
  }

  atualizar();
  setInterval(atualizar, 1000);
}



function formatarData(isoString) {
  if (!isoString) return "—";
  const d = new Date(isoString);
  return d.toLocaleDateString("pt-BR");
}

function formatarDataHora(isoString) {
  if (!isoString) return "—";
  const d = new Date(isoString);
  return d.toLocaleString("pt-BR");
}



document.addEventListener("DOMContentLoaded", () => {
  inicializarSidebarMobile();
  marcarLinkAtivo();

  
  inicializarRelogio("relogio-topbar");

  
  document.querySelector(".pagina")?.classList.add("fade-in");
});


const estilosAnimacao = document.createElement("style");
estilosAnimacao.textContent = `
  @keyframes fadeIn {
    from { opacity: 0; transform: translateY(-8px); }
    to   { opacity: 1; transform: translateY(0); }
  }
  .fade-in {
    animation: fadeIn 0.25s ease;
  }
`;
document.head.appendChild(estilosAnimacao);
