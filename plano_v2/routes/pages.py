from pathlib import Path

from flask import Blueprint, current_app, render_template, url_for

pages = Blueprint("pages", __name__)


@pages.app_context_processor
def static_assets():
    def static_asset(filename):
        """Gera uma URL que muda quando o arquivo estático é alterado."""
        asset = Path(current_app.static_folder) / filename
        version = asset.stat().st_mtime_ns if asset.is_file() else 0
        return url_for("static", filename=filename, v=version)

    return {"static_asset": static_asset}

PAGE_META = {
    "today": ("Hoje", "O que estudar agora e por quê."),
    "planning": ("Planejamento", "Organize a sua semana de estudos."),
    "formations": ("Formações", "Sua trajetória e grade curricular."),
    "studies": ("Estudos atuais", "O que está em foco agora."),
    "reviews": ("Revisões", "O que precisa ser relembrado."),
    "history": ("Histórico", "Tudo o que você realmente estudou."),
    "analytics": ("Análises", "Leituras objetivas dos seus hábitos."),
    "projects": ("Projetos", "Um módulo separado dos estudos."),
}


@pages.route("/")
def root():
    return page("today")


@pages.route("/focus")
def focus():
    return render_template("focus.html", title="Foco")


@pages.route("/<page>")
def page(page):
    if page not in PAGE_META:
        return "Página não encontrada", 404
    title, subtitle = PAGE_META[page]
    return render_template("page.html", page=page, title=title, subtitle=subtitle)
