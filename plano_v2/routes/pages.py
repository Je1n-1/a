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
    "studies": ("Minhas disciplinas", "Encontre, inicie, revise e organize suas disciplinas."),
    "reviews": ("Revisões", "O que precisa ser relembrado."),
    "history": ("Histórico", "Tudo o que você realmente estudou."),
    "analytics": ("Análises", "Leituras objetivas dos seus hábitos."),
    "projects": ("Projetos", "Um módulo separado dos estudos."),
    "settings": ("Configurações", "Limites, rotina e preferências do Plano."),
}


def render_page(page_name, **context):
    title, subtitle = PAGE_META[page_name]
    return render_template("page.html", page=page_name, title=title, subtitle=subtitle, **context)


@pages.route("/")
def root():
    return page("today")


@pages.route("/focus")
def focus():
    return render_template("focus.html", title="Foco")


@pages.route("/planning/<section>")
def planning_section(section):
    if section not in {"goals", "reviews", "settings"}:
        return "Página não encontrada", 404
    return render_page("planning", page_section=section)


@pages.route("/subjects")
def subjects():
    return render_page("studies")


@pages.route("/subjects/new")
def subject_new():
    return render_page("studies", page_section="new")


@pages.route("/subjects/<int:subject_id>")
def subject_detail(subject_id):
    return render_page("studies", subject_id=subject_id, page_section="overview")


@pages.route("/subjects/<int:subject_id>/contents")
def subject_contents(subject_id):
    return render_page("studies", subject_id=subject_id, page_section="contents")


@pages.route("/subjects/<int:subject_id>/settings")
def subject_settings(subject_id):
    return render_page("studies", subject_id=subject_id, page_section="settings")


@pages.route("/settings/<section>")
def settings_section(section):
    if section not in {"study", "availability", "integrations"}:
        return "Página não encontrada", 404
    return render_page("settings", page_section=section)


@pages.route("/reviews/<int:review_id>")
def review_detail(review_id):
    return render_page("reviews", selected_id=review_id)


@pages.route("/<page>")
def page(page):
    if page not in PAGE_META:
        return "Página não encontrada", 404
    return render_page(page)
