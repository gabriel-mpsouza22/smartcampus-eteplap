




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




function _pilhaToasts() {
  let el = document.getElementById("pilha-toasts");
  if (!el) {
    el = document.createElement("div");
    el.id = "pilha-toasts";
    el.setAttribute("aria-live", "polite");
    document.body.appendChild(el);
  }
  return el;
}

const _iconeToast = {
  erro: "i-close-circle", sucesso: "i-check-circle",
  aviso: "i-warning", info: "i-info",
};

/**
 * Mostra um toast empilhável. Se `acao` for passado ({ rotulo, ao_clicar }),
 * exibe um botão de ação (tipicamente "Desfazer") em vez de fechar sozinho
 * cedo demais — ações destrutivas devem preferir isso a um confirm().
 */
function mostrarAlerta(mensagem, tipo = "info", duracaoMs = 5000, acao = null) {
  const pilha = _pilhaToasts();
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.setAttribute("role", tipo === "erro" ? "alert" : "status");

  const nomeIcone = _iconeToast[tipo] || _iconeToast.info;
  toast.innerHTML = `
    <svg class="icon toast-icone icone-${tipo}"><use href="#${nomeIcone}"></use></svg>
    <div class="toast-corpo">
      <div>${mensagem}</div>
      ${acao ? `<button type="button" class="toast-acao">${acao.rotulo}</button>` : ""}
    </div>
    <button type="button" class="toast-fechar" aria-label="Fechar aviso">
      <svg class="icon"><use href="#i-close"></use></svg>
    </button>`;

  const remover = () => {
    toast.setAttribute("data-saindo", "");
    setTimeout(() => toast.remove(), 160);
  };

  toast.querySelector(".toast-fechar").addEventListener("click", remover);
  if (acao) {
    toast.querySelector(".toast-acao").addEventListener("click", () => {
      acao.ao_clicar();
      remover();
    });
  }

  pilha.appendChild(toast);
  if (duracaoMs > 0) setTimeout(remover, duracaoMs);
  return { fechar: remover };
}

/**
 * Diálogo de confirmação acessível (substitui window.confirm()).
 * Uso: const ok = await confirmarAcao({ titulo, texto, rotuloConfirmar, perigoso: true });
 */
function confirmarAcao({ titulo = "Confirmar ação", texto = "", rotuloConfirmar = "Confirmar", rotuloCancelar = "Cancelar", perigoso = false } = {}) {
  return new Promise((resolve) => {
    const dlg = document.createElement("dialog");
    dlg.className = "modal";
    dlg.innerHTML = `
      <div class="modal-corpo">
        <div class="modal-titulo">${titulo}</div>
        ${texto ? `<p class="modal-texto">${texto}</p>` : ""}
      </div>
      <div class="modal-acoes">
        <button type="button" class="btn btn-secundario" data-papel="cancelar">${rotuloCancelar}</button>
        <button type="button" class="btn ${perigoso ? "btn-perigo" : "btn-primario"}" data-papel="confirmar">${rotuloConfirmar}</button>
      </div>`;
    document.body.appendChild(dlg);

    const finalizar = (resultado) => {
      dlg.close();
      dlg.remove();
      resolve(resultado);
    };

    dlg.querySelector('[data-papel="cancelar"]').addEventListener("click", () => finalizar(false));
    dlg.querySelector('[data-papel="confirmar"]').addEventListener("click", () => finalizar(true));
    dlg.addEventListener("cancel", () => finalizar(false));

    dlg.showModal();
    dlg.querySelector('[data-papel="confirmar"]').focus();
  });
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



/* mantido por compatibilidade — prefira confirmarAcao() nas telas novas */
function confirmar(mensagem) {
  return confirmarAcao({ texto: mensagem });
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



function inicializarAlternarTema() {
  /* modo escuro é o único modo do sistema — nada a alternar */
}

document.addEventListener("DOMContentLoaded", () => {
  inicializarSidebarMobile();
  marcarLinkAtivo();
  inicializarAlternarTema();

  
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
