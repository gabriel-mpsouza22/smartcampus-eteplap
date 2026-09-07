(function () {
  "use strict";

  const ETAPAS = [
    { id: "boas-vindas",   label: "Boas-vindas" },
    { id: "instituicao",   label: "Instituição" },
    { id: "estrutura",     label: "Tipo de instituição" },
    { id: "turmas",        label: "Turnos e turmas" },
    { id: "funcionamento", label: "Funcionamento" },
    { id: "modulos",       label: "Módulos" },
    { id: "sinal",         label: "Sinal",  condicional: (m) => m.has("sinal") },
    { id: "iot",           label: "IoT",    condicional: (m) => m.has("iot") },
    { id: "admin",         label: "Administrador" },
    { id: "revisao",       label: "Revisão" },
    { id: "instalacao",    label: "Instalação" },
    { id: "conclusao",     label: "Conclusão" },
  ];

  // Cada escola pode ter mais de um turno (Integral, Manhã, Tarde, Noite…)
  // e cada turno tem sua PRÓPRIA estrutura: séries/módulos, cursos e
  // sufixos de turma. Isso evita o bug de cruzar tudo com tudo (ex: gerar
  // "1º ao 3º Módulo" com cursos do Integral, ou "1º ao 3º Ano" com os
  // cursos subsequentes da Noite) — cada bloco só gera combinações dentro
  // de si mesmo.
  const local = {
    tipoInstituicao: "regular",  // definido na etapa "Tipo de instituição"; usado para decidir se Curso é obrigatório
    turnoBlocos: [],       // [{ nome, rotuloSerie, series:[], cursos:[], sufixos:[] }]
    turmas: [],            // {turma, serie, curso, turno} — lista final, editável
    modulosSelecionados: new Set(),
    horarios: { padrao: [], sabado: [], prova: [] },
    iot: { agua: [], portoes: [] },
  };

  // Só escolas técnicas/ETE e faculdades organizam turmas por curso
  // (ex: "3º Ano — Redes de Computadores"). Escola regular não tem esse
  // conceito — obrigar a preencher algo aqui só pra continuar seria
  // pedir pra inventar um valor sem sentido.
  function cursosSaoObrigatorios() {
    return local.tipoInstituicao === "tecnica" || local.tipoInstituicao === "faculdade";
  }

  let indiceAtual = 0;
  let siglaEditadaManualmente = false;
  let ultimaSiglaSugerida = "";

  // Palavras que normalmente NÃO entram na sigla de uma instituição
  // brasileira (senão "Escola Municipal de Educação Infantil" viraria
  // "EMDEI" em vez de "EMEI").
  const STOPWORDS_SIGLA = new Set([
    "de", "da", "do", "das", "dos", "e", "em", "a", "o", "as", "os",
    "para", "com", "um", "uma",
  ]);

  function sugerirSigla(nome) {
    // Remove acentos (Á -> A, é -> e, etc.) ANTES de pegar as iniciais —
    // é isso que evita gerar algo como "ETEPLÁP" (com acento) a partir
    // de um nome com "Ávila": normaliza pra forma decomposta (NFD, letra
    // + acento como caracteres separados) e descarta as marcas de acento.
    const semAcento = nome.normalize("NFD").replace(/[\u0300-\u036f]/g, "");
    const palavras = semAcento.trim().split(/\s+/).filter(Boolean);
    return palavras
      .filter((p, i) => i === 0 || !STOPWORDS_SIGLA.has(p.toLowerCase()))
      .map(p => p[0])
      .join("")
      .toUpperCase();
  }

  function etapasVisiveis() {
    return ETAPAS.filter(e => !e.condicional || e.condicional(local.modulosSelecionados));
  }

  function renderProgresso() {
    const alvo = document.getElementById("lista-progresso");
    const visiveis = etapasVisiveis();
    const idxAtualVisivel = visiveis.findIndex(e => e.id === ETAPAS[indiceAtual].id);
    alvo.innerHTML = visiveis.map((e, i) => {
      let classe = "";
      if (i < idxAtualVisivel) classe = "concluido";
      if (i === idxAtualVisivel) classe = "ativo";
      return `<div class="wizard-progresso-item ${classe}"><span class="wizard-progresso-bolinha"></span>${e.label}</div>`;
    }).join("");
  }

  function mostrarEtapa(id) {
    document.querySelectorAll(".wizard-etapa").forEach(el => el.classList.remove("ativa"));
    const alvo = document.querySelector(`.wizard-etapa[data-step="${id}"]`);
    if (alvo) alvo.classList.add("ativa");
    indiceAtual = ETAPAS.findIndex(e => e.id === id);
    limparErros();
    renderProgresso();
    window.scrollTo(0, 0);
  }

  function proximaEtapaId() {
    const visiveis = etapasVisiveis();
    const atual = ETAPAS[indiceAtual].id;
    const i = visiveis.findIndex(e => e.id === atual);
    return visiveis[Math.min(i + 1, visiveis.length - 1)].id;
  }

  function etapaAnteriorId() {
    const visiveis = etapasVisiveis();
    const atual = ETAPAS[indiceAtual].id;
    const i = visiveis.findIndex(e => e.id === atual);
    return visiveis[Math.max(i - 1, 0)].id;
  }

  function mostrarErros(lista) {
    const caixa = document.getElementById("caixa-erros");
    const ul = document.getElementById("lista-erros");
    ul.innerHTML = lista.map(e => `<li>${escapeHtml(e)}</li>`).join("");
    caixa.classList.add("visivel");
    caixa.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function limparErros() {
    document.getElementById("caixa-erros").classList.remove("visivel");
  }

  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  async function salvarSecao(secao, dados) {
    const resp = await fetch("/wizard/api/estado", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ secao, dados }),
    });
    return resp.json();
  }

  // ── construção das tabelas de horário ──────────────────────────────

  function renderHorarios(chave) {
    const corpo = document.getElementById(`corpo-horarios-${chave}`);
    corpo.innerHTML = local.horarios[chave].map((h, i) => `
      <tr>
        <td><input type="time" value="${h.hora}" onchange="wz.editarHorario('${chave}',${i},'hora',this.value)" style="width:110px;"></td>
        <td><input type="text" value="${escapeHtml(h.descricao)}" onchange="wz.editarHorario('${chave}',${i},'descricao',this.value)"></td>
        <td><button class="btn btn-secundario btn-sm" onclick="wz.removerHorario('${chave}',${i})"><svg class="icon"><use href="#i-close"></use></svg></button></td>
      </tr>
    `).join("") || `<tr><td colspan="3" style="color:var(--texto-mudo);">Nenhum horário ainda.</td></tr>`;
  }

  // ── blocos de turno (séries/módulos, cursos e sufixos por turno) ────

  function renderTurnoBlocos() {
    const alvo = document.getElementById("lista-blocos-turno");
    const cursosObrigatorios = cursosSaoObrigatorios();
    alvo.innerHTML = local.turnoBlocos.map((b, i) => `
      <div class="card" style="margin-bottom:16px;">
        <div style="display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap;margin-bottom:12px;">
          <div class="campo" style="flex:1;min-width:160px;margin-bottom:0;">
            <label>Nome do turno</label>
            <input type="text" value="${escapeHtml(b.nome)}" placeholder="Ex: Integral, Noite, Manhã…"
                   onchange="wz.editarBloco(${i},'nome',this.value)">
          </div>
          <div class="campo" style="flex:1;min-width:160px;margin-bottom:0;">
            <label>Como chamar cada etapa</label>
            <input type="text" value="${escapeHtml(b.rotuloSerie)}" placeholder="Ex: Ano, Módulo, Série…"
                   onchange="wz.editarBloco(${i},'rotuloSerie',this.value)">
          </div>
          <button class="btn btn-secundario btn-sm" onclick="wz.removerBloco(${i})" title="Remover turno">
            <svg class="icon"><use href="#i-close"></use></svg> Remover turno
          </button>
        </div>

        <label style="font-size:0.78rem;font-weight:600;color:var(--texto-secundario);">${escapeHtml(b.rotuloSerie || "Séries")} deste turno</label>
        <div class="wizard-linha-adicionar">
          <input type="text" id="bloco-${i}-serie-novo" placeholder="Ex: 1º ${escapeHtml(b.rotuloSerie || 'Ano')}">
          <button class="btn btn-secundario" onclick="wz.addTagBloco(${i},'series','bloco-${i}-serie-novo')">Adicionar</button>
        </div>
        <div class="wizard-linha-adicionar" style="margin-top:6px;">
          <span class="text-xs text-mudo" style="align-self:center;">ou gere de uma vez:</span>
          <input type="number" id="bloco-${i}-serie-de" placeholder="De" min="1" style="width:64px;">
          <span class="text-xs text-mudo" style="align-self:center;">até</span>
          <input type="number" id="bloco-${i}-serie-ate" placeholder="Até" min="1" style="width:64px;">
          <button class="btn btn-secundario btn-sm" onclick="wz.gerarSequenciaSeries(${i})">
            <svg class="icon"><use href="#i-shuffle"></use></svg> Gerar (ex: 1º ao 5º ${escapeHtml(b.rotuloSerie || "Ano")})
          </button>
        </div>
        <div class="wizard-tag-lista">${tagsHtml(b.series, i, "series")}</div>

        ${cursosObrigatorios ? `
        <label style="font-size:0.78rem;font-weight:600;color:var(--texto-secundario);margin-top:10px;">Cursos deste turno</label>
        <div class="wizard-linha-adicionar">
          <input type="text" id="bloco-${i}-curso-novo" placeholder="Ex: Redes de Computadores">
          <button class="btn btn-secundario" onclick="wz.addTagBloco(${i},'cursos','bloco-${i}-curso-novo')">Adicionar</button>
        </div>
        <div class="wizard-tag-lista">${tagsHtml(b.cursos, i, "cursos")}</div>
        ` : `
        <details style="margin-top:10px;" ${b.cursos.length ? "open" : ""}>
          <summary style="cursor:pointer;font-size:0.78rem;font-weight:600;color:var(--texto-secundario);">
            + Este turno também tem cursos/ênfases (opcional)
          </summary>
          <div class="wizard-linha-adicionar" style="margin-top:8px;">
            <input type="text" id="bloco-${i}-curso-novo" placeholder="Ex: Bilíngue, Integral avançado…">
            <button class="btn btn-secundario" onclick="wz.addTagBloco(${i},'cursos','bloco-${i}-curso-novo')">Adicionar</button>
          </div>
          <div class="wizard-tag-lista">${tagsHtml(b.cursos, i, "cursos")}</div>
        </details>
        `}

        <div class="campo" style="margin-top:10px;">
          <label>Sufixos de turma (deixe em branco se não houver, ex: turmas subsequentes sem letra)</label>
          <input type="text" value="${escapeHtml((b.sufixos || []).join(', '))}" placeholder="Ex: A, B"
                 onchange="wz.editarSufixosBloco(${i}, this.value)">
        </div>

        <button class="btn btn-secundario btn-sm" onclick="wz.gerarTurmasBloco(${i})">
          <svg class="icon"><use href="#i-shuffle"></use></svg> Gerar turmas deste turno
        </button>
        <span style="font-size:0.78rem;color:var(--texto-mudo);margin-left:8px;">
          ${(() => {
            const nCursos = cursosObrigatorios ? b.cursos.length : (b.cursos.length || 1);
            const nSufixos = (b.sufixos && b.sufixos.length) || 1;
            return b.series.length && (!cursosObrigatorios || b.cursos.length)
              ? `${b.series.length} × ${nCursos} × ${nSufixos} = ${b.series.length * nCursos * nSufixos} turma(s)`
              : `defina ${cursosObrigatorios ? "séries e cursos" : "ao menos as séries"} para gerar`;
          })()}
        </span>
      </div>
    `).join("") || `<p style="color:var(--texto-mudo);">Nenhum turno adicionado ainda. Clique em "Adicionar turno" para começar.</p>`;
  }

  function tagsHtml(lista, blocoIdx, campo) {
    return lista.map((v, i) =>
      `<span class="wizard-tag">${escapeHtml(v)}<button onclick="wz.removeTagBloco(${blocoIdx},'${campo}',${i})">&times;</button></span>`
    ).join("") || `<span style="color:var(--texto-mudo);font-size:0.82rem;">Nenhum ainda.</span>`;
  }

  // ── tabela final de turmas (revisão/ajuste manual, todos os turnos juntos) ──

  function nomesTurnos() {
    return local.turnoBlocos.map(b => b.nome).filter(Boolean);
  }

  function opcoesSelect(lista, atual) {
    return lista.map(v => `<option value="${escapeHtml(v)}" ${v === atual ? "selected" : ""}>${escapeHtml(v)}</option>`).join("");
  }

  function renderTurmas() {
    const corpo = document.getElementById("corpo-tabela-turmas");
    corpo.innerHTML = local.turmas.map((t, i) => `
      <tr>
        <td><input type="text" value="${escapeHtml(t.turma)}" onchange="wz.editarTurma(${i},'turma',this.value)" style="width:200px;"></td>
        <td><input type="text" value="${escapeHtml(t.serie)}" onchange="wz.editarTurma(${i},'serie',this.value)" style="width:110px;"></td>
        <td><input type="text" value="${escapeHtml(t.curso)}" onchange="wz.editarTurma(${i},'curso',this.value)" style="width:180px;"></td>
        <td><select onchange="wz.editarTurma(${i},'turno',this.value)"><option value="">—</option>${opcoesSelect(nomesTurnos(), t.turno)}</select></td>
        <td><button class="btn btn-secundario btn-sm" onclick="wz.removerTurma(${i})"><svg class="icon"><use href="#i-close"></use></svg></button></td>
      </tr>
    `).join("") || `<tr><td colspan="5" style="color:var(--texto-mudo);">Nenhuma turma gerada ainda.</td></tr>`;
    const aviso = document.getElementById("aviso-turma-duplicada");
    if (aviso) {
      const nomes = local.turmas.map(t => t.turma.trim()).filter(Boolean);
      const duplicadas = nomes.filter((n, i) => nomes.indexOf(n) !== i);
      if (duplicadas.length) {
        aviso.textContent = `Atenção: existe(m) turma(s) com o mesmo nome (${[...new Set(duplicadas)].join(", ")}). Cada turma precisa de um nome único — ajuste antes de continuar.`;
        aviso.style.display = "";
      } else {
        aviso.style.display = "none";
      }
    }
  }

  // ── módulos ─────────────────────────────────────────────────────────

  function renderModulos() {
    const alvo = document.getElementById("cards-modulos");
    alvo.innerHTML = window.WIZARD_MODULOS.map(m => `
      <div class="wizard-card-modulo ${local.modulosSelecionados.has(m.id) ? "selecionado" : ""}" onclick="wz.toggleModulo('${m.id}')">
        <div class="wizard-card-modulo-topo">
          <span class="wizard-card-modulo-nome">${escapeHtml(m.nome)}</span>
          <input type="checkbox" ${local.modulosSelecionados.has(m.id) ? "checked" : ""} onclick="event.stopPropagation(); wz.toggleModulo('${m.id}')">
        </div>
        <div class="wizard-card-modulo-desc">${escapeHtml(m.descricao)}</div>
      </div>
    `).join("");
  }

  // ── iot ────────────────────────────────────────────────────────────

  function renderSensoresAgua() {
    const alvo = document.getElementById("lista-sensores-agua");
    alvo.innerHTML = local.iot.agua.map((s, i) => `
      <div class="wizard-tag" style="margin:4px 6px 4px 0;">${escapeHtml(s.nome)}<button onclick="wz.removerSensorAgua(${i})">&times;</button></div>
    `).join("") || `<span style="color:var(--texto-mudo);font-size:0.82rem;">Nenhum sensor ainda.</span>`;
  }

  function renderPortoes() {
    const alvo = document.getElementById("lista-portoes");
    alvo.innerHTML = local.iot.portoes.map((p, i) => `
      <div class="wizard-tag" style="margin:4px 6px 4px 0;">${escapeHtml(p.nome)}<button onclick="wz.removerPortao(${i})">&times;</button></div>
    `).join("") || `<span style="color:var(--texto-mudo);font-size:0.82rem;">Nenhum portão ainda.</span>`;
  }

  // ── revisão ────────────────────────────────────────────────────────

  function secaoRevisao(titulo, etapaId, kvs) {
    return `
      <div class="wizard-secao-revisao card">
        <div class="wizard-secao-revisao-titulo">
          ${escapeHtml(titulo)}
          <button class="btn btn-secundario btn-sm" onclick="wz.irPara('${etapaId}')">Editar</button>
        </div>
        <dl class="wizard-kv">
          ${kvs.map(([k, v]) => `<dt>${escapeHtml(k)}</dt><dd>${v}</dd>`).join("")}
        </dl>
      </div>`;
  }

  async function renderRevisao() {
    const resp = await fetch("/wizard/api/estado");
    const estado = await resp.json();
    const alvo = document.getElementById("corpo-revisao");

    let html = "";
    html += secaoRevisao("Instituição", "instituicao", [
      ["Nome", escapeHtml(estado.instituicao.nome || "—")],
      ["Sigla", escapeHtml(estado.instituicao.sigla || "—")],
      ["Localização", escapeHtml([estado.instituicao.cidade, estado.instituicao.estado].filter(Boolean).join(" / ") || "—")],
    ]);
    html += secaoRevisao("Turnos e turmas", "turmas", [
      ["Turnos", escapeHtml(nomesTurnos().join(", ") || "—")],
      ["Turmas geradas", String(local.turmas.length)],
    ]);
    html += secaoRevisao("Módulos", "modulos", [
      ["Contratados", escapeHtml([...local.modulosSelecionados].join(", ") || "—")],
    ]);
    if (local.modulosSelecionados.has("sinal")) {
      const sinal = estado.sinal || {};
      html += secaoRevisao("Sinal", "sinal", [
        ["Modo", sinal.modo === "remoto" ? "Remoto" : "Nesta máquina"],
        ["Eventos (padrão)", String(local.horarios.padrao.length)],
      ]);
    }
    if (local.modulosSelecionados.has("iot")) {
      html += secaoRevisao("IoT", "iot", [
        ["Sensores de água", String(local.iot.agua.length)],
        ["Portões", String(local.iot.portoes.length)],
        ["Ar-condicionado", document.getElementById("f-iot-ac").checked ? "Sim" : "Não"],
      ]);
    }
    html += secaoRevisao("Administrador", "admin", [
      ["Nome", escapeHtml(document.getElementById("f-admin-nome").value || "—")],
    ]);

    alvo.innerHTML = html;
  }

  // ── objeto público ─────────────────────────────────────────────────

  window.wz = {

    avancar() { mostrarEtapa(proximaEtapaId()); },
    voltar() { mostrarEtapa(etapaAnteriorId()); },
    irPara(id) { mostrarEtapa(id); },

    async salvarInstituicao() {
      const dados = {
        nome: document.getElementById("f-inst-nome").value.trim(),
        sigla: document.getElementById("f-inst-sigla").value.trim(),
        cidade: document.getElementById("f-inst-cidade").value.trim(),
        estado: document.getElementById("f-inst-estado").value.trim(),
        responsavel_implantacao: document.getElementById("f-inst-responsavel").value.trim(),
      };
      if (!dados.nome || !dados.sigla) {
        mostrarErros(["Informe ao menos o nome completo e a sigla da instituição."]);
        return;
      }
      await salvarSecao("instituicao", dados);
      wz.avancar();
    },

    async salvarEstrutura() {
      local.tipoInstituicao = document.getElementById("f-est-tipo").value;
      const dados = { tipo: local.tipoInstituicao };
      await salvarSecao("estrutura", dados);
      renderTurnoBlocos();  // cursos vira obrigatório/opcional conforme o tipo escolhido
      wz.avancar();
    },

    // ── blocos de turno ──
    adicionarBloco() {
      local.turnoBlocos.push({ nome: "", rotuloSerie: "Ano", series: [], cursos: [], sufixos: [] });
      renderTurnoBlocos();
    },
    removerBloco(i) {
      const nomeRemovido = (local.turnoBlocos[i] || {}).nome;
      local.turnoBlocos.splice(i, 1);
      local.turmas = local.turmas.filter(t => t.turno !== nomeRemovido);
      renderTurnoBlocos();
      renderTurmas();
    },
    editarBloco(i, campo, valor) {
      const nomeAntigo = local.turnoBlocos[i].nome;
      local.turnoBlocos[i][campo] = valor;
      if (campo === "nome") {
        // renomear o turno também atualiza as turmas já geradas para ele
        local.turmas.forEach(t => { if (t.turno === nomeAntigo) t.turno = valor; });
        renderTurmas();
      }
      renderTurnoBlocos();
    },
    editarSufixosBloco(i, valor) {
      local.turnoBlocos[i].sufixos = valor.split(",").map(s => s.trim()).filter(Boolean);
    },
    addTagBloco(blocoIdx, campo, inputId) {
      const input = document.getElementById(inputId);
      const v = input.value.trim();
      if (!v) return;
      if (!local.turnoBlocos[blocoIdx][campo].includes(v)) local.turnoBlocos[blocoIdx][campo].push(v);
      input.value = "";
      renderTurnoBlocos();
    },
    removeTagBloco(blocoIdx, campo, i) {
      local.turnoBlocos[blocoIdx][campo].splice(i, 1);
      renderTurnoBlocos();
    },

    gerarSequenciaSeries(blocoIdx) {
      const campoDe = document.getElementById(`bloco-${blocoIdx}-serie-de`);
      const campoAte = document.getElementById(`bloco-${blocoIdx}-serie-ate`);
      const de = parseInt(campoDe.value, 10);
      const ate = parseInt(campoAte.value, 10);
      if (!de || !ate || ate < de) {
        mostrarErros(["Informe um intervalo válido (ex: de 1 até 5)."]);
        return;
      }
      if (ate - de > 30) {
        mostrarErros(["Intervalo grande demais — confira os números."]);
        return;
      }
      const rotulo = local.turnoBlocos[blocoIdx].rotuloSerie || "Ano";
      for (let n = de; n <= ate; n++) {
        const v = `${n}º ${rotulo}`;
        if (!local.turnoBlocos[blocoIdx].series.includes(v)) local.turnoBlocos[blocoIdx].series.push(v);
      }
      campoDe.value = "";
      campoAte.value = "";
      renderTurnoBlocos();
    },

    gerarTurmasBloco(i) {
      const bloco = local.turnoBlocos[i];
      if (!bloco.nome) { mostrarErros(["Dê um nome a este turno antes de gerar as turmas."]); return; }
      const cursosObrigatorios = cursosSaoObrigatorios();
      if (bloco.series.length === 0 || (cursosObrigatorios && bloco.cursos.length === 0)) {
        const oQueFalta = cursosObrigatorios ? `ao menos uma série/${bloco.rotuloSerie || "etapa"} e um curso` : `ao menos uma série/${bloco.rotuloSerie || "etapa"}`;
        mostrarErros([`Defina ${oQueFalta} para o turno "${bloco.nome}".`]);
        return;
      }
      const sufixos = (bloco.sufixos && bloco.sufixos.length) ? bloco.sufixos : [""];
      // Escola sem conceito de "curso" (a maioria): trata como um curso
      // "em branco" só pra geração — o nome da turma final não ganha
      // esse pedaço (ver `.trim()` abaixo), então vira só "1º Ano A" em
      // vez de "1º Ano A " com um espaço sobrando de um curso vazio.
      const cursos = bloco.cursos.length ? bloco.cursos : [""];
      // remove turmas geradas anteriormente para este turno, pra não duplicar ao gerar de novo
      local.turmas = local.turmas.filter(t => t.turno !== bloco.nome);
      for (const serie of bloco.series) {
        for (const curso of cursos) {
          for (const sufixo of sufixos) {
            const numero = (serie.match(/\d+/) || [null])[0];
            const prefixoSerie = numero ? `${numero}º` : serie;
            const nomeTurma = sufixo ? `${prefixoSerie}${sufixo} ${curso}`.trim() : `${serie} ${curso}`.trim();
            local.turmas.push({ turma: nomeTurma, serie, curso, turno: bloco.nome });
          }
        }
      }
      renderTurmas();
    },
    gerarTodasAsTurmas() {
      local.turnoBlocos.forEach((_, i) => wz.gerarTurmasBloco(i));
    },

    addTurmaManual() {
      local.turmas.push({ turma: "", serie: "", curso: "", turno: local.turnoBlocos[0]?.nome || "" });
      renderTurmas();
    },
    editarTurma(i, campo, valor) { local.turmas[i][campo] = valor; },
    removerTurma(i) { local.turmas.splice(i, 1); renderTurmas(); },

    async salvarTurmas() {
      if (local.turmas.length === 0) {
        mostrarErros(["Gere ou cadastre ao menos uma turma antes de continuar."]);
        return;
      }
      const nomes = local.turmas.map(t => t.turma.trim());
      if (nomes.some(n => !n)) {
        mostrarErros(["Existe uma turma sem nome — preencha ou remova essa linha."]);
        return;
      }
      const duplicadas = nomes.filter((n, i) => nomes.indexOf(n) !== i);
      if (duplicadas.length) {
        mostrarErros([`Existem turmas com nome repetido: ${[...new Set(duplicadas)].join(", ")}. Cada turma precisa de um nome único, senão o sistema não consegue distingui-las depois.`]);
        return;
      }
      await salvarSecao("turmas", local.turmas);
      wz.avancar();
    },

    async salvarFuncionamento() {
      const dados = {
        sabado_diferente: document.getElementById("f-func-sabado").checked,
        prova_diferente: document.getElementById("f-func-prova").checked,
      };
      await salvarSecao("funcionamento", dados);
      document.getElementById("bloco-horario-sabado").style.display = dados.sabado_diferente ? "" : "none";
      document.getElementById("bloco-horario-prova").style.display = dados.prova_diferente ? "" : "none";
      wz.avancar();
    },

    toggleModulo(id) {
      if (local.modulosSelecionados.has(id)) local.modulosSelecionados.delete(id);
      else local.modulosSelecionados.add(id);
      renderModulos();
    },
    async salvarModulos() {
      if (local.modulosSelecionados.size === 0) {
        mostrarErros(["Selecione pelo menos um módulo contratado antes de continuar."]);
        return;
      }
      await salvarSecao("modulos_ativos", [...local.modulosSelecionados]);
      wz.avancar();
    },

    atualizarModoSinal() {
      const modo = document.querySelector('input[name="f-sinal-modo"]:checked').value;
      document.getElementById("campo-sinal-url").style.display = modo === "remoto" ? "" : "none";
    },
    addHorario(chave) {
      local.horarios[chave].push({ hora: "07:00", descricao: "" });
      renderHorarios(chave);
    },
    editarHorario(chave, i, campo, valor) { local.horarios[chave][i][campo] = valor; },
    removerHorario(chave, i) { local.horarios[chave].splice(i, 1); renderHorarios(chave); },

    async salvarSinal() {
      const modo = document.querySelector('input[name="f-sinal-modo"]:checked').value;
      const url = document.getElementById("f-sinal-url").value.trim();
      if (modo === "remoto" && !url) {
        mostrarErros(["Informe o endereço do computador remoto do sinal."]);
        return;
      }
      if (local.horarios.padrao.length === 0) {
        mostrarErros(["Cadastre ao menos um evento no horário padrão."]);
        return;
      }
      await salvarSecao("sinal", { modo, url });
      await salvarSecao("horarios", local.horarios);
      wz.avancar();
    },

    toggleIotBloco(qual) {
      document.getElementById(`bloco-iot-${qual}`).style.display =
        document.getElementById(`f-iot-${qual}`).checked ? "" : "none";
    },
    addSensorAgua() {
      const input = document.getElementById("f-iot-agua-novo");
      const v = input.value.trim();
      if (!v) return;
      local.iot.agua.push({ nome: v, hardware: "ESP32 + JSN-SR04T", limite_minimo: 20 });
      input.value = "";
      renderSensoresAgua();
    },
    removerSensorAgua(i) { local.iot.agua.splice(i, 1); renderSensoresAgua(); },
    addPortao() {
      const input = document.getElementById("f-iot-portao-novo");
      const v = input.value.trim();
      if (!v) return;
      local.iot.portoes.push({ nome: v });
      input.value = "";
      renderPortoes();
    },
    removerPortao(i) { local.iot.portoes.splice(i, 1); renderPortoes(); },

    async salvarIot() {
      const dados = {
        agua_ativo: document.getElementById("f-iot-agua").checked,
        agua_sensores: local.iot.agua,
        portoes_ativo: document.getElementById("f-iot-portoes").checked,
        portoes_lista: local.iot.portoes,
        portoes_horario_abertura: document.getElementById("f-iot-portoes-abertura").value,
        portoes_horario_fechamento: document.getElementById("f-iot-portoes-fechamento").value,
        ac_ativo: document.getElementById("f-iot-ac").checked,
        ac_nome: document.getElementById("f-iot-ac-nome").value.trim(),
        ac_quantidade: document.getElementById("f-iot-ac-qtd").value,
        ac_horario_ligar: document.getElementById("f-iot-ac-horario").value,
        ac_dias_semana: [0, 1, 2, 3, 4],
      };
      await salvarSecao("iot", dados);
      wz.avancar();
    },

    async salvarAdmin() {
      const dados = {
        nome: document.getElementById("f-admin-nome").value.trim(),
        senha: document.getElementById("f-admin-senha").value,
        confirmacao: document.getElementById("f-admin-confirmacao").value,
      };
      if (!dados.nome) { mostrarErros(["Informe o nome do administrador."]); return; }
      if (dados.senha.length < 6) { mostrarErros(["A senha deve ter no mínimo 6 caracteres."]); return; }
      if (dados.senha !== dados.confirmacao) { mostrarErros(["A confirmação de senha não confere."]); return; }
      await salvarSecao("admin", dados);
      await renderRevisao();
      wz.avancar();
    },

    async instalar() {
      mostrarEtapa("instalacao");
      const passos = [
        "Validando configurações", "Criando estrutura de dados", "Salvando configuração da instituição",
        "Configurando turmas", "Configurando horários", "Configurando módulos", "Criando administrador", "Finalizando",
      ];
      const lista = document.getElementById("lista-progresso-instalacao");
      lista.innerHTML = passos.map(p => `
        <div class="wizard-progresso-instalacao-item" data-passo="${escapeHtml(p)}">
          <svg class="icon icone-check"><use href="#i-clock"></use></svg>${escapeHtml(p)}
        </div>`).join("");

      const resp = await fetch("/wizard/api/instalar", { method: "POST" });
      const resultado = await resp.json();

      if (!resultado.ok) {
        const caixa = document.getElementById("erro-instalacao");
        caixa.classList.add("visivel");
        caixa.innerHTML = `<strong>Falha na etapa "${escapeHtml(resultado.etapa || "instalação")}":</strong><ul>${
          (resultado.erros || ["Erro desconhecido."]).map(e => `<li>${escapeHtml(e)}</li>`).join("")
        }</ul><button class="btn btn-primario" style="margin-top:10px;" onclick="wz.irPara('revisao')">Voltar e corrigir</button>`;
        // marca no checklist até onde chegou
        (resultado.etapas_concluidas || []).forEach(marcarPassoFeito);
        return;
      }

      (resultado.etapas_concluidas || passos).forEach(marcarPassoFeito);
      document.getElementById("conc-nome").textContent = resultado.nome_escola || "—";
      document.getElementById("conc-id").textContent = resultado.id_instalacao || "—";
      setTimeout(() => mostrarEtapa("conclusao"), 500);
    },
  };

  function marcarPassoFeito(nomePasso) {
    const el = document.querySelector(`[data-passo="${CSS.escape(nomePasso)}"]`);
    if (!el) return;
    el.classList.add("feita");
    el.querySelector("use").setAttribute("href", "#i-check-circle");
  }

  // ── inicialização ──────────────────────────────────────────────────

  document.addEventListener("DOMContentLoaded", () => {
    renderTurnoBlocos();
    renderTurmas();
    renderModulos();
    renderHorarios("padrao");
    renderHorarios("sabado");
    renderHorarios("prova");
    renderSensoresAgua();
    renderPortoes();
    mostrarEtapa("boas-vindas");

    // Sigla sugerida automaticamente a partir do nome, mas só enquanto
    // a pessoa não mexer nela na mão — a partir do primeiro edit manual,
    // o sistema para de sobrescrever (senão vira briga entre o que ela
    // digitou e o que o sistema "acha" que devia estar lá).
    const campoNome = document.getElementById("f-inst-nome");
    const campoSigla = document.getElementById("f-inst-sigla");
    if (campoNome && campoSigla) {
      campoSigla.addEventListener("input", () => {
        if (campoSigla.value !== ultimaSiglaSugerida) siglaEditadaManualmente = true;
      });
      campoNome.addEventListener("input", () => {
        if (siglaEditadaManualmente) return;
        ultimaSiglaSugerida = sugerirSigla(campoNome.value);
        campoSigla.value = ultimaSiglaSugerida;
      });
    }
  });
})();
