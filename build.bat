@echo off
REM Build de um clique do Smart Campus. Dá dois cliques neste arquivo
REM (ou rode "build.bat" no terminal) dentro da pasta do projeto.
REM
REM O que ele faz, em ordem, parando no primeiro erro:
REM   1. Cria uma venv (.venv) se ainda não existir.
REM   2. Instala/atualiza as dependências (requirements.txt).
REM   3. Roda os testes automatizados (tests\) — se algum falhar, o
REM      build NÃO continua, pra não entregar um .exe com bug de lógica
REM      conhecido pro cliente.
REM   4. Roda build_exe.py, que gera o .exe em dist_exe\SmartCampus\.

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================
echo  Smart Campus - build automatizado
echo ============================================
echo.

if not exist ".venv" (
    echo [1/4] Criando ambiente virtual (.venv)...
    python -m venv .venv
    if errorlevel 1 (
        echo ERRO: nao consegui criar a venv. Python esta instalado e no PATH?
        pause
        exit /b 1
    )
) else (
    echo [1/4] Ambiente virtual (.venv) ja existe, pulando.
)

call .venv\Scripts\activate.bat

echo.
echo [2/4] Instalando dependencias...
python -m pip install --upgrade pip >nul
pip install -r requirements.txt
if errorlevel 1 (
    echo ERRO: falha instalando dependencias. Veja a mensagem acima.
    pause
    exit /b 1
)
pip install pyinstaller >nul
if errorlevel 1 (
    echo ERRO: falha instalando o pyinstaller.
    pause
    exit /b 1
)

echo.
echo [3/4] Rodando os testes automatizados...
python -m pytest tests\ -q
if errorlevel 1 (
    echo.
    echo ============================================
    echo  TESTES FALHARAM - build CANCELADO
    echo ============================================
    echo O .exe nao foi gerado. Corrija o teste que falhou acima antes
    echo de tentar de novo - entregar um build com um bug ja conhecido
    echo pro cliente e pior do que atrasar a entrega.
    pause
    exit /b 1
)

echo.
echo [4/4] Gerando o executavel...
python build_exe.py
if errorlevel 1 (
    echo.
    echo ============================================
    echo  BUILD FALHOU
    echo ============================================
    echo Veja a mensagem do PyInstaller acima.
    pause
    exit /b 1
)

echo.
echo ============================================
echo  BUILD CONCLUIDO
echo ============================================
echo Executavel em: dist_exe\SmartCampus\SmartCampus.exe
echo.
pause
