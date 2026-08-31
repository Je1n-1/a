from flask import Blueprint, render_template

pages = Blueprint("pages", __name__)

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


@pages.route("/<page>")
def page(page):
    if page not in PAGE_META:
        return "Página não encontrada", 404
    title, subtitle = PAGE_META[page]
    return render_template("page.html", page=page, title=title, subtitle=subtitle)
