from pathlib import Path

from flask import Blueprint, current_app, render_template, url_for, redirect

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
    return formations_workspace()


@pages.route("/formations")
def formations_workspace():
    return render_template("formations.html", title="Formações")


@pages.route("/focus")
def focus():
    return render_template("today.html", title="Foco")


@pages.route('/today')
def today():
    return render_template('today.html',title='Hoje')


@pages.route('/curriculum/<int:curriculum_id>')
def curriculum_workspace(curriculum_id):
    from database.connection import connect
    from database.repositories.curriculum_workspace import subject
    with connect() as conn:
        row = subject(conn, curriculum_id)
        if not row or row['item_type'] != 'subject':
            return 'Disciplina não encontrada', 404
    return render_template('curriculum_subject.html', title='Disciplina', curriculum_id=curriculum_id)


@pages.route("/planning/<section>")
def planning_section(section):
    if section not in {"goals", "reviews", "settings"}:
        return "Página não encontrada", 404
    return render_page("planning", page_section=section)


@pages.route("/subjects")
def subjects():
    return render_template('disciplines.html',title='Disciplinas')


@pages.route('/disciplines')
def disciplines_alias():
    from flask import request
    query=request.query_string.decode('utf-8')
    return redirect('/subjects'+('?' + query if query else ''),302)


@pages.route("/subjects/new")
def subject_new():
    return render_page("studies", page_section="new")


@pages.route("/subjects/<int:subject_id>")
def subject_detail(subject_id):
    return legacy_subject_redirect(subject_id)


@pages.route("/subjects/<int:subject_id>/contents")
def subject_contents(subject_id):
    return legacy_subject_redirect(subject_id,'contents')


@pages.route("/subjects/<int:subject_id>/settings")
def subject_settings(subject_id):
    return legacy_subject_redirect(subject_id)


def legacy_subject_redirect(subject_id, tab='overview'):
    from database.connection import connect
    from database.repositories.core import one
    with connect() as conn:
        study=one(conn,'SELECT curriculum_subject_id FROM materias_estudo WHERE id=?',(subject_id,))
    if not study:
        return 'Estudo não encontrado',404
    if study['curriculum_subject_id']:
        return redirect(url_for('pages.curriculum_workspace',curriculum_id=study['curriculum_subject_id'],tab=tab),302)
    return redirect(url_for('pages.subjects',study=subject_id),302)


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
