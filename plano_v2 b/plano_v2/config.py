"""Configurações estáveis da aplicação.

O projeto pode conter um ``plano.db`` histórico na raiz.  Ele nunca é uma
fonte implícita de dados da V2: o banco ativo padrão é sempre o arquivo dentro
de ``instance/``.  Uma troca de caminho só é possível por uma configuração
explícita de ambiente, que fica registrada no diagnóstico de inicialização.
"""
from __future__ import annotations

import os
from datetime import timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


ROOT = Path(__file__).resolve().parent
INSTANCE = ROOT / "instance"
DEFAULT_DATABASE_PATH = (INSTANCE / "plano.db").resolve()
LEGACY_ROOT_DATABASE_PATH = (ROOT / "plano.db").resolve()


def _configured_database_path() -> Path:
    """Resolve o único banco ativo, sem depender do diretório de execução.

    ``PLANO_DATABASE_PATH`` é deliberadamente opt-in: ele é útil em testes e
    em instalações portáteis, mas um arquivo ``plano.db`` solto na raiz nunca
    passa a ser usado por acidente. Caminhos relativos são resolvidos a partir
    da raiz do projeto, e não do processo que iniciou o Flask.
    """
    raw_path = os.environ.get("PLANO_DATABASE_PATH", "").strip()
    if not raw_path:
        return DEFAULT_DATABASE_PATH
    configured = Path(raw_path).expanduser()
    if not configured.is_absolute():
        configured = ROOT / configured
    return configured.resolve()


DATABASE_PATH = _configured_database_path()
CURRICULUM_TEMPLATE_PATH = ROOT / "static" / "downloads" / "modelo_grade_curricular.xlsx"
DEFAULT_SESSION_MINUTES = 50
TIMEZONE = "America/Sao_Paulo"


def resolve_local_timezone():
    """Entrega o fuso do produto mesmo em Python sem pacote ``tzdata``.

    Em instalações normais, ``ZoneInfo`` preserva todas as regras históricas
    de America/Sao_Paulo. Alguns Python para Windows não trazem a base IANA;
    nesse caso a aplicação continua no horário brasileiro atual (UTC-3), com
    o mesmo nome público, em vez de cair silenciosamente em UTC.
    """
    try:
        return ZoneInfo(TIMEZONE)
    except ZoneInfoNotFoundError:
        return timezone(timedelta(hours=-3), name=TIMEZONE)


LOCAL_TIMEZONE = resolve_local_timezone()
