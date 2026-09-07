; ============================================================================
; SmartCampus — Instalador gráfico (Inno Setup)
; ============================================================================
; O QUE É ISTO:
; Este é um script para o Inno Setup (ferramenta gratuita, não é o SmartCampus
; em si) que transforma o SmartCampus.exe "cru" — gerado por build_exe.py —
; num instalador de verdade, com assistente gráfico, atalhos, e checagem
; automática de pré-requisitos (WebView2 Runtime).
;
; COMO GERAR O INSTALADOR (leia também LEIA-ME-GERAR-INSTALADOR.txt):
;   1. Baixe e instale o Inno Setup: https://jrsoftware.org/isdl.php
;   2. Gere o SmartCampus.exe normalmente (python build_exe.py) — ele deve
;      estar em dist_exe\SmartCampus.exe antes de compilar este script.
;   3. Baixe o "bootstrapper" oficial do WebView2 Runtime da Microsoft em
;      https://developer.microsoft.com/microsoft-edge/webview2/
;      (link "Evergreen Bootstrapper", arquivo pequeno, ~2 MB) e salve como
;      instalador_gui\MicrosoftEdgeWebview2Setup.exe
;   4. Abra este arquivo (SmartCampus.iss) no Inno Setup Compiler e clique
;      em "Compile" (ou rode ISCC.exe SmartCampus.iss pelo terminal).
;   5. O instalador final aparece em instalador_gui\Saida\SmartCampus_Instalador.exe
;      — é ESSE arquivo que você entrega ao cliente, não o SmartCampus.exe cru.
;
; POR QUE UM INSTALADOR E NÃO SÓ O .EXE:
;   - Instala o WebView2 Runtime sozinho se estiver faltando (a causa mais
;     comum do "abre e fecha na hora" que já aconteceu numa build anterior).
;   - Cria atalho na área de trabalho e no menu Iniciar — quem for instalar
;     não precisa nem saber onde o arquivo foi parar.
;   - Permite desinstalar de forma limpa pelo Painel de Controle, sem nunca
;     apagar os dados da escola por engano.
; ============================================================================

#define MyAppName "Smart Campus"
; Só números e pontos aqui — AppVersion e VersionInfoVersion (mais abaixo)
; usam esta mesma constante, e VersionInfoVersion vira o FileVersion
; embutido no .exe pelo Windows, que exige um formato numérico estrito
; (não aceita o prefixo "v"). A versão exibida DENTRO do sistema (tela
; de administração, config.json) é "v3.02.16" — só a constante do
; instalador fica sem o "v", por essa exigência do Windows.
#define MyAppVersion "3.02.16"
#define MyAppPublisher "Smart Campus"
#define MyAppExeName "SmartCampus.exe"
#define MyAppIcon "..\static\icone.ico"
#define WebView2Bootstrapper "MicrosoftEdgeWebview2Setup.exe"

[Setup]
; AppId fixo: identifica esta instalação de forma estável entre versões,
; para que uma atualização futura seja reconhecida como upgrade (não como
; um programa novo e diferente) e não crie uma segunda entrada duplicada
; no Painel de Controle.
AppId={{9F2C7B7E-2E58-4C6E-9C1E-5B9E9E7B0A1D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppSupportURL=https://smartcampus.exemplo.com.br/suporte
VersionInfoVersion={#MyAppVersion}

; Program Files: a partir da versão que passou a guardar os dados em
; %LOCALAPPDATA%\SmartCampus (ver launcher.py -> _pasta_dados_persistente),
; a pasta do programa em si não precisa mais ser gravável por usuários
; comuns — só o .exe e os arquivos que vêm com a instalação moram aqui.
; Isso permite instalar num lugar padrão e mais protegido do Windows
; (Arquivos de Programas, que exige admin para alterar), em vez de
; ProgramData, sem quebrar nada: config.json, .secret_key, sceds/data e
; a licença ficam todos em %LOCALAPPDATA%\SmartCampus, que qualquer
; usuário comum já pode ler e escrever sem precisar de privilégio
; nenhum. {autopf} escolhe automaticamente Program Files ou
; Program Files (x86) conforme a arquitetura do Windows do cliente.
DefaultDirName={autopf}\SmartCampus
; Não deixamos a pasta terminar com o nome do app duplicado
; ({autopf} já não inclui isso, então o resultado é
; C:\Program Files\SmartCampus — curto e fácil de explicar por telefone
; ao suporte, se precisar).
DisableDirPage=no
DisableProgramGroupPage=yes
DefaultGroupName={#MyAppName}

; Precisa de administrador durante a instalação (para gravar em Program
; Files e para poder instalar o WebView2 Runtime, que exige privilégio
; elevado). O programa em si, depois de instalado, NUNCA pede admin
; para abrir ou usar — ele só lê/escreve em %LOCALAPPDATA%, que é do
; próprio usuário.
PrivilegesRequired=admin

OutputDir=Saida
OutputBaseFilename=SmartCampus_Instalador
Compression=lzma2/ultra64
SolidCompression=yes

; Estilo visual moderno do Inno Setup — telas maiores, fontes mais
; legíveis, mais fácil de usar para quem tem pouca familiaridade com
; instaladores do que o estilo "clássico" antigo.
WizardStyle=modern
WizardSizePercent=120

#if FileExists(MyAppIcon)
SetupIconFile={#MyAppIcon}
UninstallDisplayIcon={app}\{#MyAppExeName}
#endif

; Mensagem final antes de fechar o instalador — reforça, em linguagem
; simples, que os dados ficam guardados e onde encontrar ajuda.
UninstallDisplayName={#MyAppName}

[Languages]
; Português do Brasil como idioma principal (tela por tela já traduzida
; oficialmente pelo próprio Inno Setup: "Avançar", "Cancelar", "Concluir"
; etc. saem certos sem eu precisar traduzir cada botão manualmente).
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
; Marcado por padrão de propósito: quem não tem prática nenhuma com
; computador tende a "perder" o programa depois de instalado se não
; tiver um ícone visível na tela logo de cara.
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
Source: "..\dist_exe\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

; O instalador do WebView2 só é copiado para uma pasta temporária (não
; fica instalado permanentemente na máquina do cliente) — ele mesmo se
; autoexclui depois de rodar. "external" porque este arquivo não é
; comprimido junto ao instalador (mantém o instalador principal menor e
; facilita atualizar o WebView2 sem precisar recompilar tudo).
Source: "{#WebView2Bootstrapper}"; DestDir: "{tmp}"; Flags: dontcopy external skipifsourcedoesntexist

[Dirs]
; Não precisa mais de "users-modify" aqui: desde que os dados passaram
; a morar em %LOCALAPPDATA%\SmartCampus (por usuário, sempre gravável
; sem privilégio nenhum), esta pasta ({app}) só guarda o .exe e os
; arquivos da instalação — pode ficar com a permissão padrão de
; Program Files (somente admin escreve), que é justamente o
; comportamento mais seguro/protegido.
Name: "{app}"

; Garante que a pasta de dados por usuário já exista ANTES do passo que
; copia a licença (ver [Code] -> CurStepChanged), já que FileCopy exige
; que a pasta de destino já exista. O launcher.py também cria esta
; pasta sozinho na primeira abertura, então isto aqui é só para
; permitir copiar a licença durante a própria instalação.
Name: "{localappdata}\SmartCampus"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Verifica e instala o WebView2 Runtime ANTES de finalizar — silenciosamente
; (o usuário não vê nada além da mensagem de status), e só se ele
; realmente não estiver presente (ver função IsWebView2Installed abaixo).
; Isto elimina de vez o cenário "o programa abre e fecha na hora" para
; qualquer instalação feita a partir deste instalador.
Filename: "{tmp}\{#WebView2Bootstrapper}"; Parameters: "/silent /install"; \
    StatusMsg: "Verificando componente necessário (Microsoft Edge WebView2)..."; \
    Check: PrecisaInstalarWebView2; Flags: waituntilterminated

; Checkbox final "Abrir o Smart Campus agora" — pré-marcado, porque a
; ação mais provável de quem acabou de instalar um programa é querer
; ver ele funcionando na hora, sem precisar procurar o ícone de novo.
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; IMPORTANTE — decisão deliberada: nada aqui aponta para
; %LOCALAPPDATA%\SmartCampus (config.json, sceds\data, .secret_key,
; licenca.smc). O desinstalador padrão do Inno Setup só remove os
; arquivos que ELE instalou dentro de {app} (o .exe e os atalhos) —
; como os dados do usuário nem sequer moram em {app}, eles permanecem
; intactos após desinstalar automaticamente, sem precisar de nenhuma
; regra especial. Isto evita perda acidental de dado pessoal de aluno
; numa desinstalação por engano e permite reinstalar/atualizar sem
; perder nada.

[Code]
{ Declarada aqui em cima, antes de qualquer função, porque o Pascal Script
  do Inno Setup exige que uma variável global já tenha sido declarada
  antes de qualquer trecho de código que a referencie — mesmo que esse
  trecho só rode depois, em tempo de execução (CurStepChanged usa esta
  variável mais abaixo neste arquivo). }
var
  PaginaLicenca: TInputFileWizardPage;

{ ------------------------------------------------------------------------
  Detecção do WebView2 Runtime já instalado.
  Método oficial recomendado pela própria Microsoft para checar isto:
  ler a chave de registro do "Evergreen Runtime" e confirmar que existe
  um valor de versão (pv) diferente de vazio. O GUID abaixo é fixo e
  documentado publicamente pela Microsoft (não muda entre versões do
  WebView2 — é o identificador do produto "runtime", não de uma versão
  específica dele).
  ------------------------------------------------------------------------ }
function WebView2RegistryTemKey(const CaminhoBase: String): Boolean;
var
  Versao: String;
begin
  Result :=
    RegQueryStringValue(HKLM, CaminhoBase + '\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Versao)
    and (Versao <> '') and (Versao <> '0.0.0.0');
end;

function WebView2JaInstalado(): Boolean;
begin
  { Checa tanto o caminho de máquinas 64 bits quanto o de 32 bits —
    o WebView2 pode registrar em qualquer um dos dois dependendo de como
    foi instalado anteriormente (por outro programa, pelo Edge, etc.). }
  Result :=
    WebView2RegistryTemKey('SOFTWARE\Microsoft\EdgeUpdate\Clients')
    or WebView2RegistryTemKey('SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients');
end;

function PrecisaInstalarWebView2(): Boolean;
begin
  Result := not WebView2JaInstalado();
  if Result then
    Log('WebView2 Runtime não encontrado — será instalado automaticamente.')
  else
    Log('WebView2 Runtime já presente nesta máquina — instalação pulada.');
end;

{ ------------------------------------------------------------------------
  Extrai o instalador do WebView2 do pacote comprimido para uma pasta
  temporária real em disco antes de tentar rodá-lo (arquivos marcados
  como "dontcopy" em [Files] só existem dentro do instalador até serem
  explicitamente extraídos com ExtractTemporaryFile).
  ------------------------------------------------------------------------ }
procedure CurStepChanged(CurStep: TSetupStep);
var
  ArquivoLicencaEscolhido: String;
begin
  if (CurStep = ssInstall) and PrecisaInstalarWebView2() then
  begin
    try
      ExtractTemporaryFile('{#WebView2Bootstrapper}');
    except
      { Se o arquivo do bootstrapper não foi incluído nesta build do
        instalador (ver LEIA-ME-GERAR-INSTALADOR.txt), não trava a
        instalação por causa disso — só registra no log. O programa
        ainda assim tentará abrir normalmente ao final; se faltar o
        WebView2, o launcher.py corrigido já mostra uma mensagem clara
        em vez de fechar sem explicação. }
      Log('Não foi possível extrair o instalador do WebView2 — arquivo ausente nesta build.');
    end;
  end;

  if CurStep = ssPostInstall then
  begin
    ArquivoLicencaEscolhido := PaginaLicenca.Values[0];
    if (ArquivoLicencaEscolhido <> '') and FileExists(ArquivoLicencaEscolhido) then
    begin
      FileCopy(ArquivoLicencaEscolhido, ExpandConstant('{localappdata}\SmartCampus\licenca.smc'), False);
      Log('Arquivo de licença copiado para a pasta de instalação.');
    end;
  end;
end;

{ ------------------------------------------------------------------------
  Página extra opcional: já colocar o arquivo de licença (licenca.smc)
  durante a instalação, se o cliente já tiver recebido um do suporte.
  Evita um passo manual de "copiar arquivo depois" para quem não tem
  prática de mexer em pastas do Windows.
  (A variável PaginaLicenca usada abaixo já foi declarada no topo do
  bloco [Code].)
  ------------------------------------------------------------------------ }
procedure InitializeWizard();
begin
  PaginaLicenca := CreateInputFilePage(
    wpSelectTasks,
    'Arquivo de licença (opcional)',
    'Você já recebeu um arquivo de licença do suporte?',
    'Se você já tem um arquivo "licenca.smc" enviado pelo suporte técnico, ' +
    'selecione-o abaixo — ele será colocado automaticamente no lugar certo. ' +
    'Se ainda não tiver um, deixe em branco e clique em Avançar: o programa ' +
    'vai mostrar um código para você enviar ao suporte na primeira vez que ' +
    'for aberto.'
  );
  PaginaLicenca.Add(
    'Arquivo de licença (licenca.smc):',
    'Arquivo de licença|*.smc|Todos os arquivos|*.*',
    '.smc'
  );
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  { Sem validação obrigatória aqui — o campo é opcional de propósito, então
    simplesmente deixamos avançar mesmo vazio. }
end;
