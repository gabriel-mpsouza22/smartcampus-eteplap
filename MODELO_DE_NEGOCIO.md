# Modelo de negócio — quem decide o quê no Smart Campus

Este documento registra uma regra de negócio explicada pelo Gabriel em
05/09/2026, porque ela muda o que é apropriado (ou não) tornar
configurável pelo admin da escola daqui pra frente. Vale ler antes de
adicionar qualquer configuração nova ao painel de Admin.

## Como a venda/instalação funciona

1. A **equipe de vendas/instalação** (não a escola) gera o executável e
   roda o **Wizard de instalação**.
2. No Wizard, essa equipe preenche **todas as informações de
   personalização da escola** (nome, turnos, turmas, cursos, horários
   etc.) e, principalmente, **marca quais módulos foram contratados**
   (Sinal, Biblioteca, IoT, Ocorrências, ...).
3. **O cliente final (a escola) não escolhe os módulos.** Isso é
   decidido pela equipe de instalação, de acordo com o que a escola
   está pagando no plano contratado.
4. Se um módulo não foi marcado no Wizard, ele **não pode aparecer na
   dashboard do cliente sob nenhuma circunstância** — nem no menu, nem
   por URL direta, nem em nenhuma tela de configuração.

## Como isso já é garantido no código (verificado em 05/09/2026)

A boa notícia: a arquitetura já foi construída certo desde o início
pra isso. `core/router.registrar_blueprints()` só registra no Flask os
blueprints dos módulos presentes em `modulos_ativos` (config.json,
escrito pelo Wizard) — os demais **nem existem como rota**. Não é "menu
escondido, rota acessível se você souber a URL": a rota literalmente
não é criada. Ver o comentário no próprio código:

> "Apenas os módulos presentes em modulos_ativos (config.json) são
> registrados — os demais ficam completamente indisponíveis, inclusive
> por URL direta, já que a rota nem chega a existir no Flask."

O menu lateral (`core/auth.modulos_do_usuario`) também filtra por
`modulos_ativos` como segunda camada — redundante com a primeira de
propósito (defesa em profundidade).

## Brecha encontrada e corrigida em 05/09/2026

Ao construir o sistema de **Cargos e Permissões** (para a Coordenadora
do Integral etc.), a tela de admin que monta os checkboxes de "quais
módulos este cargo pode ver" (`core/cargos.modulos_disponiveis`)
**não cruzava com `modulos_ativos`** — ou seja, o admin da escola veria
um checkbox de "Sinal" pra marcar num cargo, mesmo numa instalação
onde Sinal nunca foi contratado.

Isso **não era uma brecha de acesso real** (o filtro do menu e o
registro de rotas continuavam bloqueando de verdade), mas era
enganoso: o admin veria uma opção que não deveria nem existir aos
olhos dele. Corrigido — `modulos_disponiveis()` agora só lista módulos
que estão simultaneamente (a) no alcance do perfil-base e (b) em
`modulos_ativos` desta instalação. O seed dos 7 cargos padrão também
foi corrigido pra não nascer com módulos não contratados na lista.

## O que isso significa pra sugestões futuras

Eu tinha sugerido, numa conversa anterior, "reabrir a tela de Módulos
pra o admin ligar/desligar depois de instalado". **Essa sugestão está
descartada** — ela contradiz esta regra de negócio: dar ao admin da
escola o poder de ativar um módulo por conta própria significaria
destravar algo que ele não contratou, sem passar pela equipe de vendas.

Regra prática pra decisões futuras: **qualquer configuração nova deve
ser cotejada com "isso é uma preferência da escola sobre COMO usar o
que ela contratou, ou isso muda O QUE ela tem acesso?"** — a primeira
categoria (tipos de ocorrência, limiares de evasão, campos de
responsável no cadastro, identidade visual, calendário letivo,
cargos/permissões *dentro* dos módulos contratados) é apropriada pro
admin da escola. A segunda categoria (quais módulos existem) é
exclusiva da equipe de instalação, via Wizard, e não deve ganhar uma
tela de autoatendimento no painel do cliente.
