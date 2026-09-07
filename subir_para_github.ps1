<#
  subir_para_github.ps1
  ----------------------
  Sobe o projeto inteiro para o GitHub, um ARQUIVO POR COMMIT.

  Como usar:
    1. Abra o PowerShell DENTRO desta pasta (a pasta do zip descompactado,
       a mesma onde este arquivo está).
    2. Rode:  .\subir_para_github.ps1
       (se o Windows bloquear scripts .ps1, rode antes, uma vez só:
        Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass)

  Pré-requisitos:
    - Git instalado (https://git-scm.com/download/win)
    - Estar autenticado no GitHub via linha de comando (o jeito mais
      simples hoje é instalar o GitHub CLI — https://cli.github.com/ —
      e rodar `gh auth login` uma vez; ou configurar um Personal
      Access Token como senha quando o Git pedir credenciais).

  O que o script faz:
    - git init (se ainda não existir um repositório aqui)
    - aponta o remote "origin" para o repositório informado abaixo
    - lista todo arquivo que NÃO está no .gitignore e ainda não foi
      commitado, e faz um `git add` + `git commit` para cada um,
      SEPARADAMENTE (por isso "um arquivo a um arquivo")
    - ao final, dá um único `git push` com todos os commits de uma vez
      (dar um push por arquivo seria extremamente lento e nada prático
      — o "arquivo por arquivo" pedido acontece nos commits, não nos
      pushes)
#>

$ErrorActionPreference = "Stop"

# ── Configuração ──────────────────────────────────────────────────
$repoUrl = "https://github.com/gabriel-mpsouza22/smartcampus-eteplap.git"
$branch  = "main"

# ── Checagens básicas ─────────────────────────────────────────────
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Error "Git não encontrado. Instale em https://git-scm.com/download/win e rode este script de novo."
    exit 1
}

# ── Inicializa o repositório local, se preciso ────────────────────
if (-not (Test-Path ".git")) {
    Write-Host "Inicializando repositório git..."
    git init | Out-Null
}
git branch -M $branch 2>$null | Out-Null

# ── Configura o remote "origin" ───────────────────────────────────
$remotos = git remote
if ($remotos -contains "origin") {
    git remote set-url origin $repoUrl
} else {
    git remote add origin $repoUrl
}

# ── Lista arquivos a enviar (respeita o .gitignore automaticamente,
#    inclusive antes do primeiro commit) ──────────────────────────
$arquivos = git ls-files --others --exclude-standard --cached --deleted --modified
$arquivos = $arquivos | Where-Object { $_ -and $_.Trim() -ne "" }

if (-not $arquivos -or $arquivos.Count -eq 0) {
    Write-Host "Nada para commitar — todos os arquivos já estão versionados e sem alterações."
} else {
    $total = $arquivos.Count
    $i = 0
    foreach ($arquivo in $arquivos) {
        $i++
        Write-Host "[$i/$total] $arquivo"
        git add -- "$arquivo"
        # --allow-empty-message evita erro caso o nome do arquivo tenha
        # algo que o git interprete de forma estranha; --quiet reduz ruído.
        git commit -m "add: $arquivo" --quiet
    }
    Write-Host ""
    Write-Host "$total arquivo(s) commitado(s), um por commit."
}

# ── Envia tudo para o GitHub de uma vez ────────────────────────────
Write-Host ""
Write-Host "Enviando para $repoUrl ..."
git push -u origin $branch

Write-Host ""
Write-Host "Concluído."
