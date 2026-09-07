# Smart Campus — ETEPLAP

Sistema de gestão escolar desenvolvido para a **Escola Técnica Estadual
Prof. Lucilo Ávila Pessoa**, empacotado como programa de Windows
(`.exe`) para ser vendido e instalado em outras instituições como
produto white-label configurável por módulos.

> **Versão atual:** `v3.02.16`

## Sumário

- [Visão geral](#visão-geral)
- [Módulos](#módulos)
- [Arquitetura](#arquitetura)
- [Como o produto é vendido/instalado](#como-o-produto-é-vendidoinstalado)
- [Rodando em desenvolvimento](#rodando-em-desenvolvimento)
- [Gerando o executável e o instalador](#gerando-o-executável-e-o-instalador)
- [Licenciamento](#licenciamento)
- [Onde ficam os dados do cliente](#onde-ficam-os-dados-do-cliente)
- [Testes](#testes)
- [Estrutura de pastas](#estrutura-de-pastas)
- [Segurança](#segurança)

## Visão geral

- **Backend:** Flask (Python), com um motor de dados próprio baseado
  em arquivo (**SCEDS** — ver `sceds/`), sem depender de banco de
  dados externo.
- **Frontend:** HTML/CSS/JavaScript puro, servido pelo próprio Flask
  (sem build step de frontend).
- **Distribuição:** empacotado com PyInstaller (`build_exe.py`) e
  instalado no cliente via um instalador Inno Setup
  (`instalador_gui/SmartCampus.iss`), que também abre uma janela
  nativa via `pywebview` — para o usuário final, parece um programa
  comum do Windows, não "um site".
- **Licenciamento:** cada instalação exige uma licença assinada
  digitalmente (Ed25519), amarrada à máquina do cliente.

## Módulos

Cada instalação só tem acesso aos módulos efetivamente contratados
pela escola — isso é decidido pela equipe de vendas/instalação durante
o Wizard, não pelo admin da escola (ver
[`MODELO_DE_NEGOCIO.md`](MODELO_DE_NEGOCIO.md) para o porquê). Módulos
disponíveis hoje (`modulos/`):

| Módulo | Descrição |
|---|---|
| `porteiro` | Painel unificado da portaria (pontualidade, saídas, visitantes) |
| `pontualidade` | Controle de atrasos/entrada de alunos |
| `saidas` | Registro de saída antecipada de alunos |
| `visitantes` | Controle de acesso de visitantes |
| `secretaria_portaria` | Painel de apoio da secretaria à portaria |
| `alunos` | Cadastro de alunos |
| `ocorrencias` | Registro de ocorrências disciplinares |
| `evasao` | Prevenção e acompanhamento de evasão escolar |
| `biblioteca` | Controle de acervo e empréstimos |
| `chaves` | Controle de chaves de salas/ambientes |
| `chamados` | Chamados técnicos internos |
| `agendamento` | Agendamento de espaços/recursos |
| `sinal` | Sinal sonoro programado (troca de aula, intervalo) |
| `iot` | Monitoramento IoT |
| `monitoramento` | Painéis de acompanhamento/gráficos |

## Arquitetura

- `app.py` — cria a aplicação Flask, registra os blueprints dos
  módulos contratados (`core/router.py`) e configura o log
  (`logs/servidor.log`).
- `launcher.py` — ponto de entrada do `.exe`: sobe o `app.py` numa
  thread e abre a janela nativa (`pywebview`); também cuida de
  verificação de licença, migração de dados de versões antigas e
  criação do atalho na Área de Trabalho.
- `core/` — autenticação, cargos/permissões, auditoria, roteamento
  entre módulos, resolução de caminhos de configuração.
- `sceds/` — o motor de dados próprio (arquivos `.sceds`), incluindo
  criptografia em repouso para tabelas sensíveis (ex.: `usuarios`).
- `wizard/` — assistente de instalação usado pela equipe de
  vendas/instalação para configurar uma escola nova e escolher os
  módulos contratados.
- `admin/` — painel de administração da instalação (visível para o
  admin da escola).
- `instalador_gui/` — script Inno Setup (`SmartCampus.iss`) que gera o
  instalador `.exe` final entregue ao cliente.

## Como o produto é vendido/instalado

1. A equipe de vendas/instalação gera o executável e roda o **Wizard**
   uma única vez por escola.
2. No Wizard, preenche os dados da instituição (nome, turnos, turmas,
   cursos, horários) e marca quais módulos foram contratados.
3. A partir daí, o admin da própria escola só gerencia cargos,
   permissões e o dia a dia — não decide módulos.
4. Módulos não contratados **não existem como rota no Flask**, não
   aparecem no menu e não são acessíveis nem por URL direta.

## Rodando em desenvolvimento

```bash
pip install -r requirements.txt
python app.py
```

Isso sobe o servidor Flask diretamente (sem a janela nativa do
`launcher.py`, que só faz sentido no `.exe` empacotado). Acesse pelo
navegador no endereço/porta configurados em `core/config.json`.

## Gerando o executável e o instalador

1. `python build_exe.py` (ou `build.bat`) — empacota tudo com
   PyInstaller em `dist_exe/`.
2. Abra `instalador_gui/SmartCampus.iss` no Inno Setup Compiler e
   gere o instalador final — ver o passo a passo completo em
   `instalador_gui/LEIA-ME-GERAR-INSTALADOR.txt`.

O instalador resultante instala o programa em `Program Files` e cria
atalho na Área de Trabalho e no Menu Iniciar.

## Licenciamento

Cada instalação exige um arquivo de licença (`licenca.smc`) assinado
com uma chave privada Ed25519. Os scripts de emissão/rotação de chave
ficam fora deste repositório por segurança — **nunca commitar chaves
privadas** (ver `.gitignore`).

## Onde ficam os dados do cliente

A partir da v3.02.x, os dados de cada instalação (`config.json`,
`.secret_key`, `sceds/data/`, `licenca.smc`, logs) ficam em
`%LOCALAPPDATA%\SmartCampus` — não mais ao lado do `.exe`. Isso evita
que os dados da escola fiquem em pastas facilmente apagadas ou
sincronizadas por engano (ex.: Downloads, OneDrive). Instalações mais
antigas são migradas automaticamente na primeira abertura desta
versão.

## Testes

```bash
pytest
```

## Estrutura de pastas

```
app.py                  Aplicação Flask principal
launcher.py              Entry point do .exe (janela nativa + licença)
build_exe.py / build.bat Empacotamento com PyInstaller
core/                    Autenticação, cargos, auditoria, roteamento
sceds/                   Motor de dados próprio (arquivo, criptografado)
modulos/                 Um subpacote por módulo contratável
wizard/                  Assistente de instalação (equipe de vendas)
admin/                   Painel de administração da escola
instalador_gui/          Script Inno Setup do instalador final
static/ , templates/     Frontend (HTML/CSS/JS servidos pelo Flask)
tests/                   Suíte de testes (pytest)
_dados_semente/          Estado inicial "de fábrica" para escolas novas
```

## Segurança

Ver `AVISO_SEGURANCA_29-08-2026.txt` e `RELATORIO_PENTEST_30-08-2026.txt`
para o histórico de avaliações de segurança já realizadas. Chaves
privadas, `.secret_key`, arquivos de licença e dados reais de alunos
nunca devem ser commitados — o `.gitignore` já cobre os casos
conhecidos.
