/*
 * Motor de gráficos compartilhado do Smart Campus
 * -------------------------------------------------
 * Extraído do módulo de Monitoramento para ser reaproveitado por
 * qualquer tela que precise dos mesmos gráficos (linha suave com
 * tooltip, e ranking em barras horizontais) — hoje usado por
 * Monitoramento e Controle de Pontualidade.
 *
 * Uso:
 *   desenharLinha("id-do-container", ["Jan","Fev","Mar"], [
 *     { nome: "Atrasos", cor: "var(--grafico-1)", valores: [3, 7, 2] }
 *   ]);
 *
 *   renderRanking("id-do-container", [{nome:"2º B", total: 14}, ...], "nome", "total");
 *
 *   inicializarTooltipGraficos();  // uma vez, em DOMContentLoaded
 */

const PALETA_GRAFICOS = ["var(--grafico-1)","var(--grafico-2)","var(--grafico-3)","var(--grafico-4)","var(--grafico-5)","var(--grafico-6)","var(--grafico-7)","var(--grafico-8)"];

function renderRanking(elId, itens, chaveNome, chaveValor) {
  const el = document.getElementById(elId);
  if (!el) return;
  if (!itens || itens.length === 0) {
    el.innerHTML = `<div class="estado-vazio">Sem dados neste período.</div>`;
    return;
  }
  const max = Math.max(...itens.map(i => i[chaveValor]));
  el.innerHTML = itens.map((item, idx) => {
    const pct = max > 0 ? (item[chaveValor] / max * 100) : 0;
    const cor = PALETA_GRAFICOS[idx % PALETA_GRAFICOS.length];
    return `
      <div class="barra-item" ${item._onclick ? `onclick="${item._onclick}" style="cursor:pointer"` : ""}>
        <div class="barra-topo">
          <span class="barra-nome-wrap">
            <span class="barra-rank">${idx + 1}</span>
            <span class="barra-nome" title="${item[chaveNome]}">${item[chaveNome]}</span>
          </span>
          <span class="barra-valor">${item[chaveValor]}</span>
        </div>
        <div class="barra-trilho"><div class="barra-fill" data-pct="${pct}" style="width:0%;background:${cor};color:${cor}"></div></div>
      </div>`;
  }).join("");

  requestAnimationFrame(() => {
    el.querySelectorAll(".barra-fill").forEach(f => { f.style.width = f.dataset.pct + "%"; });
  });
}


let _ultimosGraficosLinha = {};
let _idGradiente = 0;

function desenharLinha(elId, labels, series) {
  _ultimosGraficosLinha[elId] = { labels, series };

  const el = document.getElementById(elId);
  if (!el) return;
  const h = 220, padTop = 28, padBottom = 32, padLeft = 34, padRight = 12;

  const w = Math.max(el.clientWidth || 0, 300);

  const todosValores = series.flatMap(s => s.valores);
  const max = Math.max(1, ...todosValores);

  const maxEixo = arredondarTeto(max);

  const areaW = w - padLeft - padRight;
  const areaH = h - padTop - padBottom;

  const escX = i => padLeft + (i / (labels.length - 1 || 1)) * areaW;
  const escY = v => padTop + areaH - (v / maxEixo) * areaH;

  let defs = "";
  let svgAbertura = `<svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}">`;
  let svg = "";

  const passos = 4;
  for (let i = 0; i <= passos; i++) {
    const valorEixo = Math.round(maxEixo * (1 - i / passos));
    const y = padTop + (i / passos) * areaH;
    svg += `<line x1="${padLeft}" y1="${y.toFixed(1)}" x2="${w-padRight}" y2="${y.toFixed(1)}" stroke="var(--borda)" stroke-width="1" stroke-dasharray="${i===passos ? '0' : '2 4'}"/>`;
    svg += `<text x="${padLeft-8}" y="${(y+3).toFixed(1)}" font-size="9.5" text-anchor="end" fill="var(--texto-mudo)">${valorEixo}</text>`;
  }

  series.forEach((serie, si) => {
    const pontosXY = serie.valores.map((v,i) => [escX(i), escY(v)]);
    const linhaPath = caminhoSuave(pontosXY);
    const areaPath = `${linhaPath} L${pontosXY[pontosXY.length-1][0].toFixed(1)},${(padTop+areaH).toFixed(1)} L${pontosXY[0][0].toFixed(1)},${(padTop+areaH).toFixed(1)} Z`;

    const gradId = `grad-${elId}-${si}-${_idGradiente++}`;
    defs += `<linearGradient id="${gradId}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="${serie.cor}" stop-opacity="0.32"/>
      <stop offset="100%" stop-color="${serie.cor}" stop-opacity="0"/>
    </linearGradient>`;

    svg += `<path d="${areaPath}" fill="url(#${gradId})" stroke="none"/>`;

    const comprimentoAprox = pontosXY.length * 120;
    svg += `<path d="${linhaPath}" fill="none" stroke="${serie.cor}" stroke-width="2.5"
              stroke-linejoin="round" stroke-linecap="round" class="linha-serie"
              stroke-dasharray="${comprimentoAprox}" stroke-dashoffset="${comprimentoAprox}">
              <animate attributeName="stroke-dashoffset" from="${comprimentoAprox}" to="0" dur="650ms" fill="freeze"/>
            </path>`;

    serie.valores.forEach((v,i) => {
      const cx = escX(i).toFixed(1), cy = escY(v).toFixed(1);
      svg += `<line class="linha-guia" data-guia="${elId}-${si}-${i}" x1="${cx}" y1="${padTop}" x2="${cx}" y2="${padTop+areaH}"/>`;
      svg += `<circle cx="${cx}" cy="${cy}" r="8" fill="transparent" class="ponto-grafico"
                data-valor="${v}" data-label="${labels[i]}" data-serie="${serie.nome}" data-guia-alvo="${elId}-${si}-${i}"/>`;
      svg += `<circle cx="${cx}" cy="${cy}" r="3.5" fill="${serie.cor}" stroke="var(--card)" stroke-width="1.5"
                class="ponto-visual" style="pointer-events:none; filter:drop-shadow(0 0 4px ${serie.cor});"/>`;
    });
  });

  labels.forEach((label,i) => {
    svg += `<text x="${escX(i).toFixed(1)}" y="${h-8}" font-size="9.5" text-anchor="middle" fill="var(--texto-mudo)">${label}</text>`;
  });

  svg = svgAbertura + `<defs>${defs}</defs>` + svg + `</svg>`;
  el.innerHTML = svg;
}

/* curva suave (Catmull-Rom convertida pra Bézier cúbica) — evita o visual
   "quebrado" de segmentos retos ligando os pontos */
function caminhoSuave(pontos) {
  if (pontos.length < 2) {
    const [x,y] = pontos[0] || [0,0];
    return `M${x},${y}`;
  }
  let d = `M${pontos[0][0].toFixed(1)},${pontos[0][1].toFixed(1)}`;
  for (let i = 0; i < pontos.length - 1; i++) {
    const p0 = pontos[i - 1] || pontos[i];
    const p1 = pontos[i];
    const p2 = pontos[i + 1];
    const p3 = pontos[i + 2] || p2;
    const c1x = p1[0] + (p2[0] - p0[0]) / 6;
    const c1y = p1[1] + (p2[1] - p0[1]) / 6;
    const c2x = p2[0] - (p3[0] - p1[0]) / 6;
    const c2y = p2[1] - (p3[1] - p1[1]) / 6;
    d += ` C${c1x.toFixed(1)},${c1y.toFixed(1)} ${c2x.toFixed(1)},${c2y.toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;
  }
  return d;
}

function arredondarTeto(valor) {
  if (valor <= 5) return 5;
  if (valor <= 10) return 10;
  const grandeza = Math.pow(10, Math.floor(Math.log10(valor)));
  return Math.ceil(valor / grandeza) * grandeza;
}


function inicializarTooltipGraficos() {
  let tooltip = document.getElementById("grafico-tooltip");
  if (!tooltip) {
    tooltip = document.createElement("div");
    tooltip.id = "grafico-tooltip";
    tooltip.className = "grafico-tooltip";
    document.body.appendChild(tooltip);
  }

  document.addEventListener("mouseover", (e) => {
    const alvo = e.target.closest(".ponto-grafico");
    if (!alvo) return;
    const valor = alvo.dataset.valor;
    const label = alvo.dataset.label;
    const serieNome = alvo.dataset.serie;
    tooltip.innerHTML = `${serieNome}: <b>${valor}</b><div class="tt-sub">${label}</div>`;
    tooltip.style.display = "block";
    requestAnimationFrame(() => tooltip.classList.add("visivel"));

    const guia = document.querySelector(`.linha-guia[data-guia="${alvo.dataset.guiaAlvo}"]`);
    if (guia) guia.style.opacity = "1";
  });

  document.addEventListener("mousemove", (e) => {
    if (tooltip.style.display !== "block") return;
    tooltip.style.left = (e.clientX + 14) + "px";
    tooltip.style.top  = (e.clientY - 12) + "px";
  });

  document.addEventListener("mouseout", (e) => {
    const alvo = e.target.closest(".ponto-grafico");
    if (!alvo) return;
    tooltip.classList.remove("visivel");
    setTimeout(() => { if (!tooltip.classList.contains("visivel")) tooltip.style.display = "none"; }, 120);
    const guia = document.querySelector(`.linha-guia[data-guia="${alvo.dataset.guiaAlvo}"]`);
    if (guia) guia.style.opacity = "0";
  });
}


let _timerResizeGraficos = null;
window.addEventListener("resize", () => {
  clearTimeout(_timerResizeGraficos);
  _timerResizeGraficos = setTimeout(() => {
    for (const [elId, dados] of Object.entries(_ultimosGraficosLinha)) {
      desenharLinha(elId, dados.labels, dados.series);
    }
  }, 200);
});

document.addEventListener("DOMContentLoaded", inicializarTooltipGraficos);
