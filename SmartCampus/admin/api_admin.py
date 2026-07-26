
import json
import shutil
import string
import random
import zipfile
from pathlib import Path
from datetime import datetime
from flask import Blueprint, render_template, jsonify, request, send_file

from core.auth import (
    perfil_obrigatorio, listar_usuarios, criar_usuario,
    desativar_usuario, reativar_usuario, redefinir_senha,
    MODULOS_POR_PERFIL,
)

blueprint = Blueprint("admin", __name__, template_folder="../templates/admin")

BASE = Path(__file__).resolve().parent


def _caminho_config() -> Path:
    return BASE.parent / "core" / "config.json"

def _carregar_config() -> dict:
    with open(_caminho_config(), encoding="utf-8") as f:
        return json.load(f)

def _salvar_config(cfg: dict) -> None:
    with open(_caminho_config(), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

def _get_db():
    import sys
    cfg = _carregar_config()
    base = Path(cfg["caminho_base"])
    sys.path.insert(0, str(base))
    from sceds import SCEDS
    return SCEDS(base / "sceds" / "data")

def _pasta_backup() -> Path:
    cfg = _carregar_config()
    return Path(cfg["caminho_base"]) / "backup"

def _pasta_logs() -> Path:
    cfg = _carregar_config()
    return Path(cfg["caminho_base"]) / "logs"


def gerar_senha_sugerida(nome: str = "") -> str:
    """Gera uma senha legível e razoavelmente segura, no mesmo espírito do instalador."""
    sufixo = "".join(random.choices(string.digits, k=4))
    especial = random.choice("@#$!")
    if nome:
        base = "".join(ch for ch in nome if ch.isalnum())[:6].capitalize() or "Usuario"
        return f"{base}{especial}{sufixo}"
    chars = string.ascii_letters + string.digits + "@#$!"
    return "".join(random.choices(chars, k=10))


@blueprint.route("/")
@perfil_obrigatorio("admin")
def index():
    return render_template("admin/index.html")


@blueprint.route("/usuarios")
@perfil_obrigatorio("admin")
def pagina_usuarios():
    perfis = sorted(MODULOS_POR_PERFIL.keys())
    return render_template("admin/usuarios.html", perfis=perfis)

@blueprint.route("/api/usuarios")
@perfil_obrigatorio("admin")
def api_listar_usuarios():
    return jsonify(listar_usuarios())

@blueprint.route("/api/usuarios/sugerir-senha")
@perfil_obrigatorio("admin")
def api_sugerir_senha():
    nome = request.args.get("nome", "")
    return jsonify({"senha": gerar_senha_sugerida(nome)})

@blueprint.route("/api/usuarios", methods=["POST"])
@perfil_obrigatorio("admin")
def api_criar_usuario():
    """Body: nome, perfil, senha."""
    dados  = request.get_json(force=True)
    nome   = dados.get("nome", "").strip()
    perfil = dados.get("perfil", "").strip()
    senha  = dados.get("senha", "").strip()

    try:
        registro = criar_usuario(nome, perfil, senha)
    except ValueError as e:
        return jsonify({"ok": False, "erro": str(e)}), 400

    return jsonify({"ok": True, "usuario": {k: v for k, v in registro.items() if k != "senha_hash"}}), 201

@blueprint.route("/api/usuarios/<int:usuario_id>/desativar", methods=["POST"])
@perfil_obrigatorio("admin")
def api_desativar_usuario(usuario_id: int):
    if desativar_usuario(usuario_id):
        return jsonify({"ok": True})
    return jsonify({"ok": False, "erro": "Usuário não encontrado."}), 404

@blueprint.route("/api/usuarios/<int:usuario_id>/reativar", methods=["POST"])
@perfil_obrigatorio("admin")
def api_reativar_usuario(usuario_id: int):
    if reativar_usuario(usuario_id):
        return jsonify({"ok": True})
    return jsonify({"ok": False, "erro": "Usuário não encontrado."}), 404

@blueprint.route("/api/usuarios/<int:usuario_id>/redefinir-senha", methods=["POST"])
@perfil_obrigatorio("admin")
def api_redefinir_senha(usuario_id: int):
    """Body: nova_senha (opcional — se ausente, gera uma automaticamente)."""
    dados = request.get_json(silent=True) or {}
    nova_senha = dados.get("nova_senha", "").strip()

    db = _get_db()
    usuario = db.buscar_um("usuarios", onde={"id": usuario_id})
    if not usuario:
        return jsonify({"ok": False, "erro": "Usuário não encontrado."}), 404

    if not nova_senha:
        nova_senha = gerar_senha_sugerida(usuario["nome"])

    try:
        redefinir_senha(usuario_id, nova_senha)
    except ValueError as e:
        return jsonify({"ok": False, "erro": str(e)}), 400

    return jsonify({"ok": True, "nova_senha": nova_senha})


@blueprint.route("/backup")
@perfil_obrigatorio("admin")
def pagina_backup():
    return render_template("admin/backup.html")

@blueprint.route("/api/backup/historico")
@perfil_obrigatorio("admin")
def api_backup_historico():
    """Lista os backups já realizados (pastas timestamp dentro de /backup)."""
    pasta = _pasta_backup()
    pasta.mkdir(parents=True, exist_ok=True)

    itens = []
    for sub in sorted(pasta.iterdir(), reverse=True):
        if sub.is_dir() and sub.name.startswith("backup_"):
            arquivos = list(sub.glob("*.sceds"))
            tamanho_total = sum(a.stat().st_size for a in arquivos)
            zip_existe = (pasta / f"{sub.name}.zip").exists()
            itens.append({
                "nome":          sub.name,
                "data_hora":     sub.name.replace("backup_", ""),
                "total_tabelas": len(arquivos),
                "tamanho_kb":    round(tamanho_total / 1024, 1),
                "zip_disponivel": zip_existe,
            })
    return jsonify(itens[:30])

@blueprint.route("/api/backup/executar", methods=["POST"])
@perfil_obrigatorio("admin")
def api_backup_executar():
    """Executa um backup completo de todas as tabelas do SCEDS."""
    db = _get_db()
    agora = datetime.now().strftime("%Y%m%d_%H%M%S")
    nome_pasta = f"backup_{agora}"
    destino = _pasta_backup() / nome_pasta
    destino.mkdir(parents=True, exist_ok=True)

    try:
        arquivos = db.backup_completo(destino)
    except Exception as e:
        return jsonify({"ok": False, "erro": f"Falha ao copiar tabelas: {e}"}), 500

    zip_path = _pasta_backup() / f"{nome_pasta}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for arq in destino.glob("*.sceds"):
            zf.write(arq, arcname=arq.name)

    return jsonify({
        "ok": True,
        "nome": nome_pasta,
        "total_tabelas": len(arquivos),
        "mensagem": f"Backup concluído com {len(arquivos)} tabela(s).",
    }), 201

@blueprint.route("/api/backup/download/<nome>")
@perfil_obrigatorio("admin")
def api_backup_download(nome: str):
    """Envia o arquivo .zip de um backup específico para download."""
    nome_seguro = Path(nome).name
    zip_path = _pasta_backup() / f"{nome_seguro}.zip"
    if not zip_path.exists():
        return jsonify({"ok": False, "erro": "Backup não encontrado."}), 404
    return send_file(zip_path, as_attachment=True, download_name=f"{nome_seguro}.zip")

@blueprint.route("/api/backup/<nome>", methods=["DELETE"])
@perfil_obrigatorio("admin")
def api_backup_remover(nome: str):
    """Remove um backup antigo (pasta + zip) para liberar espaço."""
    nome_seguro = Path(nome).name
    pasta = _pasta_backup() / nome_seguro
    zip_path = _pasta_backup() / f"{nome_seguro}.zip"

    if not pasta.exists() and not zip_path.exists():
        return jsonify({"ok": False, "erro": "Backup não encontrado."}), 404

    if pasta.exists():
        shutil.rmtree(pasta)
    if zip_path.exists():
        zip_path.unlink()

    return jsonify({"ok": True})


@blueprint.route("/configuracoes")
@perfil_obrigatorio("admin")
def pagina_configuracoes():
    return render_template("admin/configuracoes.html")

@blueprint.route("/api/configuracoes")
@perfil_obrigatorio("admin")
def api_obter_configuracoes():
    return jsonify(_carregar_config())

@blueprint.route("/api/configuracoes", methods=["PUT"])
@perfil_obrigatorio("admin")
def api_salvar_configuracoes():
    """
    Body: porta_api, host_api (ambos opcionais — só altera o que for enviado).
    Alterações exigem reiniciar o servidor manualmente para ter efeito.
    """
    dados = request.get_json(force=True)
    cfg = _carregar_config()

    if "porta_api" in dados:
        try:
            porta = int(dados["porta_api"])
            if not (1 <= porta <= 65535):
                raise ValueError
            cfg["porta_api"] = porta
        except (TypeError, ValueError):
            return jsonify({"ok": False, "erro": "Porta inválida."}), 400

    if "host_api" in dados:
        host = str(dados["host_api"]).strip()
        if host:
            cfg["host_api"] = host

    _salvar_config(cfg)
    return jsonify({"ok": True, "config": cfg, "aviso": "Reinicie o servidor (app.py) para aplicar as mudanças."})

@blueprint.route("/api/logs")
@perfil_obrigatorio("admin")
def api_logs():
    """Retorna as últimas N linhas do log do servidor. Query: linhas (padrão 100)."""
    linhas_qtd = request.args.get("linhas", 100, type=int)
    linhas_qtd = max(10, min(linhas_qtd, 1000))

    caminho_log = _pasta_logs() / "servidor.log"
    if not caminho_log.exists():
        return jsonify({"linhas": [], "erro": "Arquivo de log ainda não existe."})

    with open(caminho_log, encoding="utf-8", errors="replace") as f:
        todas = f.readlines()

    ultimas = [l.rstrip("\n") for l in todas[-linhas_qtd:]]
    return jsonify({"linhas": ultimas, "total_arquivo": len(todas)})

@blueprint.route("/api/status-sistema")
@perfil_obrigatorio("admin")
def api_status_sistema():
    """Informações gerais para o painel: espaço usado, quantidade de tabelas, versão."""
    cfg = _carregar_config()
    db = _get_db()

    pasta_dados = Path(cfg["caminho_base"]) / "sceds" / "data"
    tamanho_dados = sum(f.stat().st_size for f in pasta_dados.glob("*.sceds")) if pasta_dados.exists() else 0

    return jsonify({
        "versao":            cfg.get("versao", "?"),
        "caminho_base":      cfg.get("caminho_base"),
        "total_tabelas":     len(db.listar_tabelas()),
        "tamanho_dados_kb":  round(tamanho_dados / 1024, 1),
    })
