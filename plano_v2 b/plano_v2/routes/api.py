"""Rotas HTTP da API do Plano.

Este módulo funciona como a camada de transporte entre o frontend e a camada
de serviços, concentrada principalmente em ``services.core``.

Responsabilidades principais:
- receber parâmetros de URL, query string, formulário e JSON;
- abrir conexões com o banco quando necessário;
- encaminhar cada requisição para a regra de negócio correspondente;
- transformar erros de domínio em respostas HTTP padronizadas;
- disponibilizar downloads e exportações gerados pelo sistema.

As regras de negócio devem permanecer em ``services.core`` sempre que
possível. Este arquivo deve se limitar à adaptação entre HTTP e domínio.
"""
from datetime import timedelta
from io import BytesIO
import sqlite3
from zipfile import ZIP_DEFLATED, ZipFile

from flask import Blueprint, Response, jsonify, request, send_file

from config import CURRICULUM_TEMPLATE_PATH
from database.connection import connect, database_health
from database.migrations import migration_status
from database.study_diagnostics import diagnose_studies, reconcile_studies
from services import core
from services.grade_import import preview, preview_paste


api = Blueprint("api", __name__, url_prefix="/api")


# Impede clientes antigos de manipularem sessões criadas pelo novo fluxo de estudo manual.
@api.before_request
def protect_manual_focus():
    """Bloqueia alterações indevidas em sessões do fluxo manual de foco."""
    # Compatibilidade: uma sessão em modo manual pertence ao fluxo da página Hoje.
    # O bloqueio impede que telas antigas do planejador alterem esse estado.
    if request.method in {'POST','PUT'} and request.path.startswith('/api/focus/sessions/'):
        ident=(request.view_args or {}).get('ident')
        if ident:
            with connect() as conn:
                row=conn.execute('SELECT manual_mode FROM sessoes_foco WHERE id=?',(ident,)).fetchone()
                if row and row['manual_mode']:
                    return jsonify({'error':'Esta sessão usa o estudo manual. Retome pela página Hoje.','code':'manual_focus_only'}),409


# Normaliza o corpo da requisição, aceitando JSON ou dados de formulário.
def body(): return request.get_json(silent=True) or request.form.to_dict()
# Padroniza respostas JSON simples usadas pelos helpers da API.
def respond(value, status=200): return jsonify(value), status
# Executa uma operação de domínio e converte exceções conhecidas em respostas HTTP consistentes.
def run(operation):
    """Executa uma operação com conexão de banco e traduz erros para HTTP.

    ``operation`` recebe a conexão SQLite aberta e deve retornar um valor
    serializável em JSON. Erros de domínio preservam código, status, bloqueios
    e detalhes; erros de validação e integridade recebem respostas padronizadas.
    """
    try:
        with connect() as conn: return respond(operation(conn))
    except core.DomainError as error:
        payload = {"error": str(error), "code": error.code}
        if error.blockers is not None:
            payload["blockers"] = error.blockers
        if error.details is not None:
            payload["details"] = error.details
        return respond(payload, error.status)
    except ValueError as error: return respond({"error":str(error),"code":"validation_error"},400)
    except sqlite3.IntegrityError: return respond({"error":"Não foi possível salvar porque os dados conflitam com um registro existente.","code":"integrity_error"},409)


# Executa uma operação que produz bytes e monta a resposta HTTP de download.
def download(operation, mimetype, filename):
    """Executa uma operação binária e devolve seu resultado como download."""
    try:
        with connect() as conn:
            payload = operation(conn)
        response = Response(payload, mimetype=mimetype)
        response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
    except core.DomainError as error: return respond({"error":str(error),"code":error.code},error.status)
    except ValueError as error: return respond({"error":str(error),"code":"validation_error"},400)
    except sqlite3.IntegrityError: return respond({"error":"Não foi possível preparar a exportação porque os dados conflitam com um registro existente.","code":"integrity_error"},409)



# =============================================================================
# INICIALIZAÇÃO E DIAGNÓSTICOS
# Dados iniciais da aplicação e ferramentas locais de verificação/recuperação.
# =============================================================================
# Carrega, em uma única chamada, o conjunto inicial de dados usado pela interface.
@api.get("/bootstrap")
def bootstrap():
    def operation(conn):
        # O bootstrap inclui o dia atual e os seis dias seguintes para preencher
        # rapidamente as áreas semanais da interface sem chamadas adicionais.
        today=core._local_now().date(); end=today+timedelta(days=6)
        return {"formations":core.formations(conn),"studies":core.studies(conn),"recommendation":core.recommendation(conn),"reviews":core.reviews(conn),"analytics":core.analytics(conn),"planned":core.planned(conn,today.isoformat(),end.isoformat())}
    return run(operation)


# Expõe informações seguras de diagnóstico do banco, migrations e estudos legados.
@api.get("/diagnostics")
def diagnostics():
    """Status seguro do banco e das migrations para suporte local."""
    return run(lambda conn: {
        "database": database_health(),
        "migrations": migration_status(),
        "legacy_studies": diagnose_studies(conn),
    })


# Consulta ou reconcilia inconsistências detectadas em registros de estudo.
@api.route("/diagnostics/studies", methods=["GET", "POST"])
def study_diagnostics():
    if request.method == "GET":
        return run(lambda conn: diagnose_studies(conn, request.args.get("date")))
    return run(lambda conn: reconcile_studies(conn, body(), body().get("date")))



# =============================================================================
# FORMAÇÕES
# Cadastro, arquivamento, restauração, remoção e inspeção de dependências das formações.
# =============================================================================
# Lista formações ou cria uma nova formação, conforme o método HTTP.
@api.route("/formations",methods=["GET","POST"])
def formation_collection():
    if request.method == "GET":
        state = request.args.get("state")
        if state is None:
            state = "all" if request.args.get("archived") == "1" else "active"
        return run(lambda conn: core.formations(conn, state))
    return run(lambda conn: core.create_formation(conn,body()))
# Atualiza ou remove uma formação específica.
@api.route("/formations/<int:ident>",methods=["PATCH","DELETE"])
def formation_item(ident):
    return run(lambda conn: core.change_formation(conn,ident,body()) if request.method=="PATCH" else core.delete_formation(conn,ident) or {"deleted":True})
# Executa ações de ciclo de vida da formação: arquivar, restaurar ou destruir.
@api.post("/formations/<int:ident>/<action>")
def formation_action(ident,action):
    data = body()
    if action == "archive":
        return run(lambda conn: core.archive_formation(conn, ident, data.get("study_policy", "archive_studies")))
    if action == "restore":
        return run(lambda conn: core.restore_formation(conn, ident, data.get("restore_studies")))
    if action == "destroy":
        return run(lambda conn: core.destroy(conn, "formation", ident, data.get("confirmation"), data.get("include_dependencies")))
    return respond({"error":"Ação de formação inválida."},400)
# Retorna dependências que podem bloquear a remoção de uma formação.
@api.get("/formations/<int:ident>/dependencies")
def formation_dependencies(ident): return run(lambda conn: core.formation_dependencies(conn, ident))



# =============================================================================
# GRADE CURRICULAR E DISCIPLINAS
# Gerenciamento da grade, importação, conteúdos, avaliações, equivalências e histórico acadêmico.
# =============================================================================
# Lista a grade curricular associada à formação informada.
@api.get("/formations/<int:formation_id>/curriculum")
def curriculum(formation_id): return run(lambda conn: core.curriculum(conn,formation_id,request.args.get("archived")=="1"))
# Fornece a visão gerencial da grade aplicando filtros recebidos pela query string.
@api.get("/formations/<int:formation_id>/curriculum/management")
def curriculum_management(formation_id):
    filters = {key: request.args.get(key) for key in ("q", "period", "academic_status", "review_status", "visibility", "quick", "sort", "item_type") if request.args.get(key) is not None}
    return run(lambda conn: core.curriculum_management(conn, formation_id, filters))
# Cria manualmente um item de grade dentro de uma formação.
@api.post("/formations/<int:formation_id>/curriculum")
def curriculum_create(formation_id): return run(lambda conn: core.create_curriculum(conn,formation_id,body()))
# Simula alterações em lote da grade antes da confirmação.
@api.post("/formations/<int:formation_id>/curriculum/batch/preview")
def curriculum_batch_preview(formation_id): return run(lambda conn: core.curriculum_batch_preview(conn, formation_id, body()))
# Aplica alterações em lote previamente definidas para a grade.
@api.post("/formations/<int:formation_id>/curriculum/batch")
def curriculum_batch(formation_id): return run(lambda conn: core.curriculum_batch(conn, formation_id, body()))
# Procura possíveis disciplinas duplicadas dentro da formação.
@api.get("/formations/<int:formation_id>/curriculum/duplicates")
def curriculum_duplicates(formation_id): return run(lambda conn: core.duplicate_candidates(conn, formation_id))
# Lista candidatos estruturais usados em operações de organização da grade.
@api.get("/formations/<int:formation_id>/curriculum/structural-candidates")
def curriculum_structural_candidates(formation_id): return run(lambda conn: core.structural_candidates(conn, formation_id))
# Mescla ocorrências curriculares preservando explicitamente os dados escolhidos pelo usuário.
@api.post("/formations/<int:formation_id>/curriculum/merge")
def curriculum_merge(formation_id):
    data = body()
    return run(lambda conn: core.merge_curriculum(conn, formation_id, data.get("primary_id"), data.get("duplicate_ids"), data.get("preserve"), data.get("confirmation")))
# Entrega o modelo oficial de planilha utilizado para importação de grade curricular.
@api.get("/curriculum/template")
def curriculum_template():
    if not CURRICULUM_TEMPLATE_PATH.is_file():
        return respond({"error":"O modelo oficial de grade não está disponível neste momento.","code":"curriculum_template_missing"}, 404)
    return send_file(
        CURRICULUM_TEMPLATE_PATH,
        as_attachment=True,
        download_name="modelo_grade_curricular.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
# Lê um arquivo enviado e gera a prévia da importação sem persistir a grade.
@api.post("/formations/<int:formation_id>/curriculum/preview")
def curriculum_preview(formation_id):
    def operation(conn):
        # Valida a formação antes de processar o arquivo enviado. A prévia pode
        # analisar o conteúdo, mas não deve persistir a grade neste momento.
        core._get(conn,"formacoes",formation_id)
        upload=request.files.get("file")
        if not upload or not upload.filename: raise core.DomainError("Selecione um arquivo.")
        result = preview(upload, upload.filename, request.form.get("sheet") or request.args.get("sheet"))
        return core.curriculum_import_preview(conn, formation_id, result)
    return run(operation)
# Gera a mesma prévia de importação a partir de texto colado pelo usuário.
@api.post("/formations/<int:formation_id>/curriculum/preview/paste")
def curriculum_preview_paste(formation_id):
    data = body()
    return run(lambda conn: core.curriculum_import_preview(conn, formation_id, preview_paste(data.get("text"))))
# Persiste os itens de grade que foram confirmados após a etapa de prévia.
@api.post("/formations/<int:formation_id>/curriculum/import")
def curriculum_import(formation_id):
    data = body()
    return run(lambda conn: core.import_curriculum(conn, formation_id, data.get("items", []), data.get("confirmed")))
# Consulta, atualiza ou remove uma ocorrência específica da grade curricular.
@api.route("/curriculum/<int:ident>",methods=["GET","PATCH","DELETE"])
def curriculum_item(ident):
    if request.method == "GET": return run(lambda conn: core.curriculum_detail(conn, ident))
    return run(lambda conn: core.update_curriculum(conn,ident,body()) if request.method=="PATCH" else core.delete_curriculum(conn,ident) or {"deleted":True})
# Consulta ou altera configurações de planejamento ligadas à disciplina curricular.
@api.route("/curriculum/<int:ident>/schedule-settings", methods=["GET","PATCH"])
def curriculum_schedule_settings(ident):
    return run(lambda conn: core.curriculum_schedule_settings(conn, ident) if request.method == "GET" else core.update_curriculum(conn, ident, body()))
# Lista conteúdos da disciplina ou adiciona um novo conteúdo.
@api.route("/curriculum/<int:ident>/contents", methods=["GET","POST"])
def curriculum_contents(ident):
    return run(lambda conn: core.contents(conn, ident, request.args.get("archived") == "1") if request.method == "GET" else core.create_content(conn, ident, body()))
# Consulta ou redistribui o esforço planejado entre conteúdos da disciplina.
@api.route("/curriculum/<int:ident>/contents/distribution", methods=["GET", "POST"])
def curriculum_content_distribution(ident):
    return run(lambda conn: core.topic_effort_summary_for_curriculum(conn, ident) if request.method == "GET" else core.distribute_topic_effort(conn, "curriculum", ident, body()))
# Persiste a ordem manual dos conteúdos vinculados à disciplina.
@api.post("/curriculum/<int:ident>/contents/reorder")
def curriculum_content_reorder(ident): return run(lambda conn: core.reorder_topics(conn, "curriculum", ident, body()))
# Retorna o histórico de alterações de um conteúdo específico.
@api.get("/contents/<int:ident>/history")
def content_history(ident): return run(lambda conn: core.content_history(conn, ident))
# Atualiza ou remove um conteúdo da disciplina.
@api.route("/contents/<int:ident>", methods=["PATCH","DELETE"])
def content_item(ident): return run(lambda conn: core.update_content(conn, ident, body()) if request.method == "PATCH" else core.delete_content(conn, ident) or {"deleted": True})
# Arquiva ou restaura um conteúdo sem apagá-lo definitivamente.
@api.post("/contents/<int:ident>/<action>")
def content_action(ident, action):
    if action == "archive": return run(lambda conn: core.archive_content(conn, ident))
    if action == "restore": return run(lambda conn: core.archive_content(conn, ident, True))
    return respond({"error":"Ação de conteúdo inválida."}, 400)
# Consulta o resumo de avaliações da disciplina ou registra uma nova avaliação.
@api.route("/curriculum/<int:ident>/evaluations", methods=["GET","POST"])
def curriculum_evaluations(ident):
    return run(lambda conn: core.evaluation_summary(conn, ident) if request.method == "GET" else core.create_evaluation(conn, {**body(), "curriculum_subject_id": ident}))
# Retorna dependências relacionadas a uma ocorrência curricular.
@api.get("/curriculum/<int:ident>/dependencies")
def curriculum_dependencies(ident): return run(lambda conn: core.curriculum_dependencies(conn, ident))
# Gerencia o compartilhamento explícito do mesmo estudo pessoal entre disciplinas equivalentes.
@api.route("/curriculum/<int:ident>/shared-study", methods=["GET", "POST", "DELETE"])
def curriculum_shared_study(ident):
    """Prévia e confirmação explícita para equivalências entre formações.

    A rota é propositalmente separada das alterações acadêmicas da grade: o
    vínculo compartilha só o estudo pessoal canônico, nunca estado, nota ou
    prazo institucional da ocorrência curricular.
    """
    if request.method == "GET":
        return run(lambda conn: core.curriculum_shared_study(conn, ident))
    if request.method == "POST":
        return run(lambda conn: core.link_curriculum_shared_study(conn, ident, body()))
    return run(lambda conn: core.unlink_curriculum_shared_study(conn, ident, body()))
# Retorna o histórico de mudanças de status acadêmico da disciplina.
@api.get("/curriculum/<int:ident>/history")
def curriculum_history(ident): return run(lambda conn: core.curriculum_status_history(conn, ident))
# Monta a linha do tempo completa de eventos relacionados à disciplina.
@api.get("/curriculum/<int:ident>/timeline")
def curriculum_timeline(ident): return run(lambda conn: core.curriculum_timeline(conn, ident))
# Registra uma alteração manual do status acadêmico da disciplina.
@api.post("/curriculum/<int:ident>/status")
def curriculum_status(ident): return run(lambda conn: core.change_curriculum_status(conn, ident, body(), "manual", body().get("notes")))
# Configura o comportamento de revisão associado à disciplina.
@api.post("/curriculum/<int:ident>/review")
def curriculum_review(ident): return run(lambda conn: core.set_curriculum_review(conn, ident, body()))
# Executa ações de ciclo de vida da disciplina: iniciar, arquivar, restaurar ou destruir.
@api.post("/curriculum/<int:ident>/<action>")
def curriculum_action(ident,action):
    if action == "start": return run(lambda conn: core.start_curriculum_study(conn, ident, body()))
    if action == "archive": return run(lambda conn: core.archive_curriculum(conn,ident))
    if action == "restore": return run(lambda conn: core.archive_curriculum(conn,ident,True))
    if action == "destroy": return run(lambda conn: core.destroy(conn,"curriculum",ident,body().get("confirmation"),body().get("include_dependencies")))
    return respond({"error":"Ação de disciplina inválida."},400)
# Cria ou vincula um estudo pessoal a uma disciplina curricular existente.
@api.post("/curriculum/<int:ident>/add-study")
def curriculum_add_study(ident): return run(lambda conn: core.add_curriculum_study(conn,ident,body()))



# =============================================================================
# ESTUDOS PESSOAIS E TÓPICOS
# Matérias de estudo independentes, metas, recomendações, tópicos e dependências.
# =============================================================================
# Lista estudos pessoais com filtros ou cria um estudo independente da grade.
@api.route("/studies",methods=["GET","POST"])
def study_collection():
    if request.method == "POST": return run(lambda conn: core.create_personal_study(conn,body()))
    visibility = request.args.get("visibility")
    return run(lambda conn: core.studies(
        conn, request.args.get("archived")=="1", request.args.get("week_reference"), visibility,
        request.args.get("formation_id"), request.args.get("q"), request.args.get("review_status"),
    ))
# Gera uma prévia antes de registrar um novo estudo pessoal.
@api.post("/studies/preview")
def study_registration_preview():
    return run(lambda conn: core.study_registration_preview(conn, body()))
# Retorna os dados completos de uma matéria de estudo.
@api.get("/studies/<int:ident>")
def study_detail(ident): return run(lambda conn: core.subject_detail(conn,ident))
# Atualiza ou exclui um estudo pessoal específico.
@api.route("/studies/<int:ident>",methods=["PATCH","DELETE"])
def study_item(ident): return run(lambda conn: core.update_study(conn,ident,body()) if request.method=="PATCH" else core.delete_study(conn,ident) or {"deleted":True})
# Atualiza a meta diária de estudo definida para a matéria.
@api.patch("/studies/<int:ident>/daily-goal")
def study_daily_goal(ident): return run(lambda conn: core.update_daily_goal(conn, ident, body()))
# Consulta ou recalcula uma recomendação adaptativa para a matéria.
@api.route("/studies/<int:ident>/recommendation", methods=["GET", "POST"])
def study_recommendation(ident):
    return run(lambda conn: core.adaptive_recommendation(conn, ident, request.method == "POST"))
# Retorna o histórico de recomendações adaptativas já produzidas.
@api.get("/studies/<int:ident>/recommendations")
def study_recommendation_history(ident): return run(lambda conn: core.adaptive_recommendation_history(conn, ident))
# Registra uma observação textual associada à matéria.
@api.post("/studies/<int:ident>/observations")
def study_observation(ident): return run(lambda conn: core.add_study_observation(conn, ident, body()))
# Registra a decisão do usuário sobre uma recomendação gerada anteriormente.
@api.post("/studies/<int:ident>/recommendations/<int:snapshot_id>/decision")
def study_recommendation_decision(ident, snapshot_id):
    return run(lambda conn: core.accept_study_recommendation(conn, ident, snapshot_id, body()))
# Lista vínculos que podem impedir a exclusão ou alteração destrutiva do estudo.
@api.get("/studies/<int:ident>/dependencies")
def study_dependencies(ident): return run(lambda conn: core.study_dependencies(conn, ident))
# Executa ações de ciclo de vida do estudo, incluindo conclusão, pausa, restauração e destruição.
@api.post("/studies/<int:ident>/<action>")
def study_action(ident,action):
    data = body()
    if action == "finish": return run(lambda conn: core.finish_study(conn,ident,data.get("result"),data.get("final_score")))
    if action == "archive": return run(lambda conn: core.archive_study(conn,ident))
    if action == "restore": return run(lambda conn: core.archive_study(conn,ident,True))
    if action == "pause": return run(lambda conn: core.pause_study(conn,ident))
    if action == "resume": return run(lambda conn: core.pause_study(conn,ident,True))
    if action == "remove-current": return run(lambda conn: core.remove_current_study(conn,ident,data.get("resolution", data.get("academic_status", "available")),data.get("cancel_future_blocks", True)))
    if action == "destroy": return run(lambda conn: core.destroy(conn,"study",ident,data.get("confirmation"),data.get("include_dependencies")))
    return respond({"error":"Ação de estudo inválida."},400)
# Cria um agrupamento interno associado à matéria de estudo.
@api.post("/studies/<int:ident>/groups")
def group_create(ident): return run(lambda conn: core.create_group(conn,ident,body()))
# Abre uma nova tentativa acadêmica preservando o histórico anterior.
@api.post("/studies/<int:ident>/new-attempt")
def study_new_attempt(ident): return run(lambda conn: core.new_academic_attempt(conn,ident,body()))
# Cria um novo tópico dentro da matéria de estudo.
@api.post("/studies/<int:ident>/topics")
def topic_create(ident): return run(lambda conn: core.create_topic(conn,ident,body()))
# Consulta ou distribui o esforço planejado entre os tópicos da matéria.
@api.route("/studies/<int:ident>/topics/distribution", methods=["GET", "POST"])
def study_topic_distribution(ident):
    return run(lambda conn: core.topic_effort_summary_for_study(conn, ident) if request.method == "GET" else core.distribute_topic_effort(conn, "study", ident, body()))
# Salva a ordem manual dos tópicos da matéria.
@api.post("/studies/<int:ident>/topics/reorder")
def study_topic_reorder(ident): return run(lambda conn: core.reorder_topics(conn, "study", ident, body()))
# Atualiza os dados de um tópico existente.
@api.patch("/topics/<int:ident>")
def topic_item(ident): return run(lambda conn: core.update_topic(conn,ident,body()))
# Arquiva ou restaura um tópico sem removê-lo definitivamente.
@api.post("/topics/<int:ident>/<action>")
def topic_action(ident, action):
    if action == "archive": return run(lambda conn: core.archive_topic(conn, ident))
    if action == "restore": return run(lambda conn: core.archive_topic(conn, ident, True))
    return respond({"error":"Ação de tópico inválida."}, 400)
# Consulta ou substitui as dependências/pré-requisitos de um tópico.
@api.route("/topics/<int:ident>/dependencies", methods=["GET", "PUT"])
def topic_dependencies(ident):
    if request.method == "GET":
        return run(lambda conn: {"topic": core._get(conn, "topicos", ident), "prerequisite_topic_ids": core._topic_dependencies_map(conn, [ident]).get(ident, [])})
    return run(lambda conn: core.set_topic_dependencies(conn, ident, body()))



# =============================================================================
# HISTÓRICO DE SESSÕES
# Sessões já registradas e correções posteriores de duração e pausas.
# =============================================================================
# Consulta o histórico de sessões em um intervalo ou registra uma sessão manual.
@api.route("/sessions",methods=["GET","POST"])
def session_collection(): return run(lambda conn: core.history(conn,request.args.get("start"),request.args.get("end")) if request.method=="GET" else core.create_session(conn,body()))
# Consulta, corrige ou exclui uma sessão de estudo já registrada.
@api.route("/sessions/<int:ident>",methods=["GET","PATCH","DELETE"])
def session_item(ident):
    if request.method == "GET": return run(lambda conn: core.session_detail(conn, ident))
    if request.method == "PATCH": return run(lambda conn: core.update_session(conn,ident,body()))
    return run(lambda conn: core.delete_session(conn,ident) or {"deleted":True})
# Adiciona uma correção de pausa a uma sessão histórica.
@api.post("/sessions/<int:ident>/breaks")
def session_break_create(ident): return run(lambda conn: core.add_session_break_correction(conn, ident, body()))
# Corrige os dados de uma pausa já registrada.
@api.patch("/session-breaks/<int:ident>")
def session_break_update(ident): return run(lambda conn: core.update_session_break(conn, ident, body()))



# =============================================================================
# SESSÃO DE FOCO ATIVA
# Ciclo de vida do cronômetro persistente usado durante o estudo em tempo real.
# =============================================================================
# Retorna a sessão de foco atualmente ativa, se existir.
@api.get("/focus/active")
def focus_active(): return run(core.active_focus_session)
# Inicia uma nova sessão de foco persistida no backend.
@api.post("/focus/sessions")
def focus_start(): return run(lambda conn: core.start_focus_session(conn, body()))
# Retorna um snapshot atualizado de uma sessão de foco específica.
@api.get("/focus/sessions/<int:ident>")
def focus_session(ident): return run(lambda conn: core._focus_snapshot(conn, core._focus_row(conn, ident)))
# Pausa uma sessão de foco e registra o instante da pausa.
@api.post("/focus/sessions/<int:ident>/pause")
def focus_pause(ident): return run(lambda conn: core.pause_focus_session(conn, ident, body()))
# Retoma uma sessão pausada e atualiza seu estado persistido.
@api.post("/focus/sessions/<int:ident>/resume")
def focus_resume(ident): return run(lambda conn: core.resume_focus_session(conn, ident, body()))
# Recupera uma sessão que precisa ser reconciliada após interrupção ou recarregamento.
@api.post("/focus/sessions/<int:ident>/recover")
def focus_recover(ident): return run(lambda conn: core.recover_focus_session(conn, ident, body()))
# Salva a anotação associada à sessão de foco em andamento.
@api.put("/focus/sessions/<int:ident>/note")
def focus_note(ident): return run(lambda conn: core.save_focus_note(conn, ident, body()))
# Finaliza a sessão de foco e consolida o estudo realizado.
@api.post("/focus/sessions/<int:ident>/finish")
def focus_finish(ident): return run(lambda conn: core.finish_focus_session(conn, ident, body()))
# Cancela a sessão de foco conforme as regras definidas no domínio.
@api.post("/focus/sessions/<int:ident>/cancel")
def focus_cancel(ident): return run(lambda conn: core.cancel_focus_session(conn, ident, body()))
# Retorna apenas as pausas registradas para uma sessão de foco.
@api.get("/focus/sessions/<int:ident>/breaks")
def focus_breaks(ident): return run(lambda conn: core._focus_snapshot(conn, core._focus_row(conn, ident))["breaks"])



# =============================================================================
# ANOTAÇÕES DE ESTUDO
# Criação, autosave, finalização e exportação das anotações produzidas durante o estudo.
# =============================================================================
# Lista notas usando filtros de matéria, tópico, período e status ou cria uma nova nota.
@api.route("/notes", methods=["GET", "POST"])
def note_collection():
    if request.method == "GET":
        selected_date = request.args.get("date")
        return run(lambda conn: core.notes(
            conn,
            request.args.get("study_subject_id") or request.args.get("subject_id"),
            request.args.get("topic_id"),
            request.args.get("start") or selected_date,
            request.args.get("end") or selected_date,
            request.args.get("status"),
        ))
    return run(lambda conn: core.create_note(conn, body()))


# Consulta, salva automaticamente ou exclui uma anotação específica.
@api.route("/notes/<int:ident>", methods=["GET", "PATCH", "DELETE"])
def note_item(ident):
    if request.method == "GET":
        return run(lambda conn: core.note_detail(conn, ident))
    if request.method == "PATCH":
        return run(lambda conn: core.autosave_note(conn, ident, body()))
    return run(lambda conn: core.delete_note(conn, ident) or {"deleted": True})


# Marca a anotação como finalizada e aplica as regras de fechamento definidas no domínio.
@api.post("/notes/<int:ident>/finalize")
def note_finalize(ident):
    return run(lambda conn: core.finalize_note(conn, ident, body()))


# Exporta uma anotação individual como arquivo Markdown.
@api.get("/notes/<int:ident>/export")
def note_export(ident):
    exported = {}
    # O nome retornado é ASCII seguro para o cabeçalho Content-Disposition;
    # o conteúdo Markdown permanece em UTF-8 e preserva os acentos.
    try:
        with connect() as conn:
            exported.update(core.note_markdown(conn, ident))
        response = Response(exported["markdown"], mimetype="text/markdown")
        response.headers["Content-Disposition"] = f'attachment; filename="{exported["filename"]}"'
        return response
    except core.DomainError as error: return respond({"error":str(error),"code":error.code},error.status)
    except ValueError as error: return respond({"error":str(error),"code":"validation_error"},400)


# Empacota várias anotações em Markdown dentro de um ZIP compatível com o fluxo do Obsidian.
@api.post("/notes/export/obsidian")
def notes_obsidian_export():
    selected = body().get("ids", body().get("note_ids"))
    def operation(conn):
        # O pacote é criado inteiramente em memória; nenhum arquivo temporário
        # precisa ser gravado no disco do servidor.
        archive = BytesIO()
        with ZipFile(archive, "w", compression=ZIP_DEFLATED) as bundle:
            for item in core.notes_for_obsidian_export(conn, selected):
                bundle.writestr(item["filename"], item["markdown"].encode("utf-8"))
        return archive.getvalue()
    return download(operation, "application/zip", "anotacoes-obsidian.zip")



# =============================================================================
# AVALIAÇÕES E REVISÕES
# Registro de avaliações, listagem de revisões e conclusão de revisões individuais.
# =============================================================================
# Lista avaliações por estudo/disciplina ou registra uma nova avaliação.
@api.route("/evaluations",methods=["GET","POST"])
def evaluation_collection(): return run(lambda conn: core.evaluations(conn,request.args.get("study_id"),request.args.get("curriculum_id")) if request.method=="GET" else core.create_evaluation(conn,body()))
# Atualiza ou remove uma avaliação existente.
@api.route("/evaluations/<int:ident>",methods=["PATCH","DELETE"])
def evaluation_item(ident): return run(lambda conn: core.update_evaluation(conn,ident,body()) if request.method=="PATCH" else core.delete_evaluation(conn,ident) or {"deleted":True})
# Lista revisões atualmente registradas pelo sistema.
@api.get("/reviews")
def review_collection(): return run(core.reviews)
# Conclui uma revisão registrando avaliação, duração e observações.
@api.post("/reviews/<int:ident>/complete")
def review_complete(ident):
    data = body()
    return run(lambda conn: core.complete_review(conn,ident,data.get("rating"),data.get("duration_seconds"),data.get("notes")))



# =============================================================================
# CAMPANHAS DE REVISÃO
# Campanhas com período definido e integração com o motor de planejamento.
# =============================================================================
# Lista campanhas de revisão ou cria uma nova campanha.
@api.route("/review-campaigns", methods=["GET", "POST"])
def review_campaign_collection():
    return run(lambda conn: core.review_campaigns(conn, request.args.get("status")) if request.method == "GET" else core.create_review_campaign(conn, body()))
# Simula uma campanha e seu planejamento dentro de uma transação temporária.
@api.post("/review-campaigns/preview")
def review_campaign_preview():
    def operation(conn):
        # A prévia reutiliza a mesma lógica de criação da campanha real, mas
        # isola todas as alterações em um SAVEPOINT temporário.
        conn.execute("SAVEPOINT preview_review_campaign")
        try:
            created = core.create_review_campaign(conn, body())
            campaign = created["campaign"]
            first = max(core._date(campaign["start_date"]), core._local_now().date())
            days = (core._date(campaign["end_date"]) - first).days + 1
            preview = core.generate_plan(conn, first.isoformat(), min(93, max(1, days)))
            return {"campaign": created, "preview": preview, "persisted": False}
        finally:
            # Independentemente do resultado, a simulação nunca deve persistir.
            conn.execute("ROLLBACK TO SAVEPOINT preview_review_campaign")
            conn.execute("RELEASE SAVEPOINT preview_review_campaign")
    return run(operation)
# Consulta os detalhes ou atualiza uma campanha de revisão existente.
@api.route("/review-campaigns/<int:ident>", methods=["GET", "PATCH"])
def review_campaign_item(ident):
    return run(lambda conn: core.review_campaign_detail(conn, ident) if request.method == "GET" else core.update_review_campaign(conn, ident, body()))
# Altera o estado da campanha entre pausada, ativa, concluída e cancelada.
@api.post("/review-campaigns/<int:ident>/<action>")
def review_campaign_action(ident, action):
    statuses = {"pause": "paused", "resume": "active", "complete": "completed", "cancel": "cancelled"}
    if action not in statuses: return respond({"error": "Ação de campanha inválida."}, 400)
    return run(lambda conn: core.set_review_campaign_status(conn, ident, statuses[action]))



# =============================================================================
# DISPONIBILIDADE
# Disponibilidade recorrente, exceções e intervalos específicos por data.
# =============================================================================
# Consulta a disponibilidade semanal ou registra uma nova configuração recorrente.
@api.route("/availability",methods=["GET","POST"])
def availability_collection(): return run(core.availability if request.method=="GET" else lambda conn:core.set_availability(conn,body()))
# Aplica várias definições de disponibilidade em uma única operação.
@api.post("/availability/batch")
def availability_batch(): return run(lambda conn:core.set_availability_batch(conn,body()))
# Copia uma configuração de disponibilidade conforme as regras do domínio.
@api.post("/availability/copy")
def availability_copy(): return run(lambda conn:core.copy_availability(conn,body()))
# Atualiza ou exclui uma disponibilidade semanal existente.
@api.route("/availability/<int:ident>",methods=["PATCH","DELETE"])
def availability_item(ident): return run(lambda conn: core.update_availability(conn,ident,body()) if request.method=="PATCH" else core.remove(conn,"disponibilidades_semanais",ident) or {"deleted":True})
# Consulta ou cria exceções pontuais à disponibilidade normal.
@api.route("/availability-exceptions",methods=["GET","POST"])
def availability_exceptions(): return run(lambda conn:core.availability_exceptions(conn,request.args.get("start"),request.args.get("end")) if request.method=="GET" else core.set_availability_exception(conn,body()))
# Atualiza ou remove uma exceção de disponibilidade.
@api.route("/availability-exceptions/<int:ident>",methods=["PATCH","DELETE"])
def availability_exception_item(ident): return run(lambda conn:core.update_availability_exception(conn,ident,body()) if request.method=="PATCH" else core.remove(conn,"excecoes_disponibilidade",ident) or {"deleted":True})
# Consulta ou cria intervalos pontuais de disponibilidade em datas específicas.
@api.route("/availability/intervals", methods=["GET", "POST"])
def availability_intervals():
    return run(lambda conn: core.availability_intervals(conn, request.args.get("start"), request.args.get("end")) if request.method == "GET" else core.set_availability_interval(conn, body()))
# Atualiza ou exclui um intervalo pontual de disponibilidade.
@api.route("/availability/intervals/<int:ident>", methods=["PATCH", "DELETE"])
def availability_interval_item(ident):
    return run(lambda conn: core.update_availability_interval(conn, ident, body()) if request.method == "PATCH" else core.remove(conn, "disponibilidades_intervalos", ident) or {"deleted": True})
# Resolve a disponibilidade efetiva de uma data após considerar regras e exceções.
@api.get("/availability/days/<selected_date>")
def availability_day(selected_date): return run(lambda conn: core.availability_day(conn, selected_date))
# Remove personalizações de uma data e restaura seu comportamento padrão.
@api.post("/availability/days/<selected_date>/reset")
def availability_day_reset(selected_date): return run(lambda conn: core.reset_availability_date(conn, selected_date))

# =============================================================================
# PLANEJAMENTO E BLOCOS PLANEJADOS
# Blocos manuais e endpoints do motor de geração, prévia, aplicação e calendário.
# =============================================================================
# Lista blocos planejados de um período ou cria um novo bloco manual.
@api.route("/planned",methods=["GET","POST"])
def planned_collection():
    today = core._today()
    return run(lambda conn: core.planned(conn,request.args.get("start",today),request.args.get("end",(core._local_now().date()+timedelta(days=6)).isoformat())) if request.method=="GET" else core.create_planned(conn,body()))
# Remove os blocos planejados de uma data específica conforme as regras do domínio.
@api.delete("/planned/day/<scheduled_date>")
def planned_day_delete(scheduled_date):
    return run(lambda conn: core.delete_planned_day(conn, scheduled_date))
# Consulta, atualiza ou exclui um bloco planejado individual.
@api.route("/planned/<int:ident>",methods=["GET","PATCH","DELETE"])
def planned_item(ident):
    if request.method=="GET": return run(lambda conn:core.planned_detail(conn,ident))
    return run(lambda conn: core.update_planned(conn,ident,body()) if request.method=="PATCH" else core.remove(conn,"sessoes_planejadas",ident) or {"deleted":True})
# Move um bloco planejado para outra data/horário preservando seu vínculo.
@api.post("/planned/<int:ident>/reschedule")
def planned_reschedule(ident): return run(lambda conn:core.reschedule_planned(conn,ident,body()))
# Gera o planejamento para o período solicitado.
@api.post("/planning/generate")
def planning_generate(): return run(lambda conn: core.generate_plan(conn,body().get("start",core._today()),int(body().get("days",7))))
# Mantém o endpoint de geração inteligente usando atualmente o mesmo motor de geração.
@api.post("/planning/generate-smart")
def planning_generate_smart():
    # Compatibilidade: este endpoint ainda existe com o nome histórico
    # "generate-smart", mas atualmente utiliza o mesmo motor de generate.
    return run(lambda conn: core.generate_plan(conn,body().get("start",core._today()),int(body().get("days",7))))
# Monta uma prévia de planejamento para conferência antes da aplicação.
@api.post("/planning/preview")
def planning_preview(): return run(lambda conn: core.create_planning_preview(conn, body()))
# Aplica ao banco um planejamento inteligente previamente definido.
@api.post("/planning/apply")
def planning_apply():
    return run(lambda conn: core.apply_smart_plan(conn, body()))
# Aplica uma versão específica do planejamento respeitando o controle de versão.
@api.post("/planning/apply-versioned")
def planning_apply_versioned(): return run(lambda conn: core.apply_versioned_plan(conn, body()))
# Calcula a capacidade disponível de estudo para o intervalo solicitado.
@api.get("/planning/capacity")
def planning_capacity(): return run(lambda conn: core.planning_capacity(conn, request.args.get("start", core._today()), request.args.get("end", (core._local_now().date()+timedelta(days=6)).isoformat())))
# Lista itens elegíveis ao planejamento aplicando filtros opcionais.
@api.get("/planning/items")
def planning_items():
    return run(lambda conn: core.planning_items(
        conn, request.args.get("start", core._today()),
        request.args.get("end", (core._local_now().date()+timedelta(days=6)).isoformat()),
        request.args.get("formation_id"), request.args.get("item_id"), request.args.get("kind"),
    ))
# Calcula a distribuição considerada ideal pelo motor para o intervalo informado.
@api.get("/planning/ideal")
def planning_ideal(): return run(lambda conn: core.planning_ideal(conn, request.args.get("start", core._today()), request.args.get("end", (core._local_now().date()+timedelta(days=6)).isoformat())))
# Transforma dados do planejamento em eventos consumidos pela visualização de calendário.
@api.get("/planning/calendar-events")
def planning_calendar_events(): return run(lambda conn: core.planning_calendar_events(conn, request.args.get("start", core._today()), request.args.get("end", (core._local_now().date()+timedelta(days=6)).isoformat())))

# =============================================================================
# HOJE, BUSCA E ANÁLISES
# Visão diária, recomendação global, busca e indicadores analíticos.
# =============================================================================
# Monta a visão consolidada da página Hoje.
@api.get("/today")
def today(): return run(core.today_overview)
# Retorna a recomendação geral de estudo produzida pelo domínio.
@api.get("/recommendation")
def recommendation(): return run(core.recommendation)
# Executa a busca global do sistema usando o texto fornecido na query string.
@api.get("/search")
def search(): return run(lambda conn: core.search(conn, request.args.get("q")))
# Retorna o conjunto principal de indicadores usados na página de análises.
@api.get("/analytics")
def analytics(): return run(core.analytics)
# Calcula indicadores de carga de estudo para o período e filtros selecionados.
@api.get("/analytics/workload")
def analytics_workload(): return run(lambda conn: core.analytics_workload(conn, request.args.get("start"), request.args.get("end"), request.args.get("formation_id"), request.args.get("item_id"), request.args.get("kind")))
# Retorna um resumo analítico, opcionalmente referenciado a uma data específica.
@api.get("/analytics/summary")
def analytics_summary(): return run(lambda conn: core.analytics_summary(conn, request.args.get("date")))
# Retorna dados analíticos detalhados filtrados por período, formação, item, campanha e finalidade.
@api.get("/analytics/detailed")
def analytics_detailed():
    return run(lambda conn: core.analytics_detailed(
        conn,
        request.args.get("start"), request.args.get("end"),
        request.args.get("formation_id"), request.args.get("item_id") or request.args.get("study_subject_id"),
        request.args.get("campaign_id"), request.args.get("purpose"),
    ))


# =============================================================================
# PROJETOS E CONFIGURAÇÕES
# Projetos pessoais, tarefas e preferências globais do aplicativo.
# =============================================================================
# Lista projetos ou cria um novo projeto pessoal.
@api.route("/projects",methods=["GET","POST"])
def project_collection(): return run(lambda conn: core.projects(conn,request.args.get("archived")=="1") if request.method=="GET" else core.create_project(conn,body()))
# Consulta, atualiza ou remove um projeto específico.
@api.route("/projects/<int:ident>",methods=["GET","PATCH","DELETE"])
def project_item(ident):
    if request.method == "GET": return run(lambda conn: core.project_detail(conn,ident))
    return run(lambda conn: core.update_project(conn,ident,body()) if request.method=="PATCH" else core.remove(conn,"projetos",ident) or {"deleted":True})
# Arquiva ou restaura um projeto sem excluir seu histórico.
@api.post("/projects/<int:ident>/<action>")
def project_action(ident, action): return run(lambda conn: core.archive_project(conn,ident,action=="restore"))
# Adiciona uma tarefa dentro de um projeto.
@api.post("/projects/<int:ident>/tasks")
def project_task(ident): return run(lambda conn: core.add_project_task(conn,ident,body()))
# Atualiza ou remove uma tarefa existente do projeto.
@api.route("/project-tasks/<int:ident>",methods=["PATCH","DELETE"])
def project_task_item(ident): return run(lambda conn: core.update_project_task(conn,ident,body()) if request.method=="PATCH" else core.remove(conn,"projeto_tarefas",ident) or {"deleted":True})
# Consulta ou salva as configurações gerais do Plano.
@api.route("/settings",methods=["GET","PUT"])
def settings(): return run(core.settings if request.method=="GET" else lambda conn: core.save_settings(conn,body()))
