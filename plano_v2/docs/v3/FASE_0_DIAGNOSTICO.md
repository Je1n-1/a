# Plano V3 — Fase 0: diagnóstico e base de verificação

Data: 10/10/2026, fuso America/Sao_Paulo. Base: `a/plano_v2`.

## 1. Escopo, estado e conclusão

Esta etapa executa a Fase 0 do documento `PLANO_V3_REFATORACAO_TECNICA_COMPLETA.md`. Não implementa a V3 nem altera comportamento, migrations ou registros do banco pessoal. Próxima etapa proposta: V3 isolada, com aprovação para a Fase 1.

- Raiz Git: `C:/Users/jeanm/OneDrive/Desktop/repositório_site_estudos/a`; aplicação em `plano_v2`.
- Branch inicial `main`, árvore limpa; commit observado `75cc28f` (`exclusao app v2 b`). Branch criada: `refactor/study-tracker-v3`. Nenhum commit/push feito nesta etapa.
- A cópia `plano_v2 b` já não existe no checkout atual. Não foi recuperada, incorporada ou usada para migrations.
- Não foi encontrado `AGENTS.md` no projeto. O ambiente `.venv` da conversa anterior já não existia; foi recriado e as cinco dependências do `requirements.txt` foram instaladas.
- A correção anterior de `renderFormations` (`!selected ? "" : ...`) já integra a base recebida. A tela vazia funciona no navegador; esse erro não foi reintroduzido nem corrigido novamente.
- O banco pessoal contém estrutura íntegra, mas nenhum curso, disciplina, estudo, foco ou sessão histórica. Há apenas registros iniciais de configuração: 10 em `configuracoes`, 1 em `calendar_integrations`, 15 em `schema_migrations`. A existência dessa linha de integração não prova uma conta conectada; credenciais não foram inspecionadas.

**Conclusão:** é possível reaproveitar o parser e os contratos de persistência do relógio. Copiar os grandes módulos completos para a V3 manteria o acoplamento que se quer retirar. A V3 deve ter dados e execução isolados e um caminho direto da disciplina ao cronômetro.

## 2. Segurança e banco ativo

`PLANO_DATABASE_PATH` não estava definido nos escopos processo, usuário ou máquina. Não havia servidor nas portas 5051/5052 na inspeção inicial. O caminho padrão foi confirmado por leitura de `config.py`, sem importar `app.py` contra o banco pessoal:

`C:\Users\jeanm\OneDrive\Desktop\repositório_site_estudos\a\plano_v2\instance\plano.db`

- Tamanho: 536.576 bytes; 42 tabelas; migrations 1–15, última `0015_interactive_planning_engine`.
- `PRAGMA integrity_check`: `ok`; `foreign_key_check`: zero violações.
- Um único `.db` encontrado no projeto, excluindo dependências. Nenhum WAL/SHM, backup anterior ou segundo banco encontrado nessa busca. Não foi realizada busca indiscriminada no computador, OneDrive remoto ou lixeira.
- Backup pela API `sqlite3.Connection.backup()`, com a origem aberta em `mode=ro`. Cópia conferida por integridade, FKs, todas as contagens e versões/checksums das migrations.
- Backup físico, fora do projeto e do OneDrive:

`C:\Users\jeanm\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\Plano\backups\plano-v2-before-v3-20261010-110837.db`

O Windows redireciona o `LocalAppData` do processo para o cache local do pacote Codex. O caminho físico acima foi resolvido e verificado. Uma primeira execução de auditoria também gerou backup íntegro antes de interromper na investigação do cabeçalho CSV; ele foi preservado. A cópia de referência é a de 11:08:37 indicada acima.

SHA-256 do banco pessoal antes e depois de **todos** os testes:

`64d27a914070a2abe783001162ca2f4bdbb8b8dc4319f930ab0c4bdd984602a6`

O hash permaneceu igual; não houve migration, restauração ou inclusão de registros no banco pessoal. Os dados fictícios estão somente em bancos isolados em `C:\Users\jeanm\AppData\Local\Plano\v3-audit\20261010-110837` (com o correspondente redirecionamento físico do Windows).

Não há bancos rastreados pelo Git. O `.gitignore` foi ampliado para bancos, arquivos auxiliares SQLite e `backups/`. O risco de sincronização de um SQLite aberto no OneDrive é uma consideração para o desenho futuro, não evidência de corrupção neste banco. A proposta é colocar os dados V3 em diretório local explícito, sem mover a V2 automaticamente.

## 3. Mapa do fluxo e dependências

| Tela/caso | Cliente e HTTP | Persistência e dependências |
|---|---|---|
| Hoje `/` | `routes/pages.py` → `templates/page.html` → `renderToday()` em `static/js/app.js:980`; GET `/api/today`, `/api/reviews`, `/api/daily-results/{date}` | Consulta agenda, capacidade, resultados diários e sugestões. Não é uma página puramente de gravação de estudos. |
| Formações | `renderFormations()` → GET `/api/formations`, `/api/formations/{id}/curriculum/management`; POST/PATCH formações | `formacoes`, `disciplinas_grade`; serviços no `core.py`, incluindo estado acadêmico, progresso e planejamento. |
| Prévia de importação | `openCurriculumImport()` → POST multipart `/api/formations/{id}/curriculum/preview` ou `/preview/paste` | `grade_import.preview()` / `preview_paste()` extraem e normalizam; `curriculum_import_preview()` consulta duplicados. A prévia não insere disciplinas. |
| Confirmar importação | `openCurriculumImportReview()` → POST `/api/formations/{id}/curriculum/import` | `import_curriculum()` valida seleção, confirmação, linhas e duplicados; escreve `disciplinas_grade` na transação de `database.connection.connect()`. |
| Converter para estudo | POST `/api/curriculum/{id}/add-study` → `add_curriculum_study()` (`core.py:2076`) | Cria/reutiliza `materias_estudo`, depende de acesso acadêmico e `canonical_links`; carrega configurações de esforço/planejamento. Importar a grade sozinho não cria esse estudo. |
| Relógio `/focus` | Template próprio + `focus.js`; GET `/api/studies`, `/api/focus/active`; POST `/api/focus/sessions`; GET por ID; pause/resume/recover/finish/cancel; PUT note | `sessoes_foco.study_subject_id` aponta a `materias_estudo`, não diretamente à grade. `focus_tracking.py` registra pausas, versões e vínculos com histórico. |
| Encerrar relógio | `finish_focus_session()` (`core.py:3765`) → `create_session()` | Transição condicional e repetição idempotente; cria `sessoes_estudo`, associa pausas/notas. Também tem caminhos de tópicos, revisões, objetivos, recomendações e replanejamento. Preservar garantias sem transportar esses caminhos extras. |
| Histórico `/history` | `renderHistory()` → GET `/api/sessions?start=...&end=...` | `history()` (`core.py:6790`) usa `LIMIT 100`, sem paginação HTTP. Totais da tela dependem do subconjunto retornado. |
| Exportação histórica | Listener `data-export` (`app.js:4294`) busca GET `/api/sessions` sem filtros | CSV é montado no navegador, limitado aos 100 registros; não conserva filtro da tela, sem BOM e sem neutralização explícita de fórmulas. |
| Análises `/analytics` | `renderAnalytics()` → summary, detailed, workload, formations, studies, review-campaigns | Seis chamadas na abertura observada; mistura leitura de estudo real com capacidade, planejamento, domínio e campanhas. `analytics_workload()` não é consulta exclusiva de tempo efetivo. |

Relação principal: `formacoes → disciplinas_grade → materias_estudo → sessoes_foco → sessoes_estudo`. Há vínculos canônicos e tabelas filhas de pausas, notas, tópicos e correções. Para dados legados, essa cadeia exige mapeamento, não substituição de IDs por coincidência.

`services/core.py` importa diretamente `smart_planning`, `adaptive_planning`, `interactive_planning`, `analytics_insights`, `google_calendar`, `canonical_links` e `focus_tracking`. Até endpoints aparentemente simples compartilham esse módulo. A validação de sessão exige matéria acessível; conclusão de tópico pode disparar resolução de blocos futuros. O parser `grade_import.py` é bem mais isolado e não importa planejamento.

## 4. Reproduções HTTP em banco isolado

Executadas por `docs/v3/audit_phase0.py`, com `Flask.test_client`, sem importar o app pessoal. Evidências completas em `evidence.json` e `audit_run.log`.

| Cenário executado | Resultado observado |
|---|---|
| Banco novo + repetir migrations | 15 versões aplicadas; segunda execução aplica zero; integridade e FKs OK. |
| XLSX oficial multipart | HTTP 200; três linhas reconhecidas e zero selecionadas; GET da grade ainda vazio. |
| Confirmar pela API com todas desmarcadas | HTTP 200; zero inseridas, três ignoradas. Nenhum registro de disciplina criado. |
| Selecionar as três e confirmar | HTTP 200; três inseridas. |
| Repetir importação | HTTP 200; zero novas, três duplicadas ignoradas. |
| Recriar aplicação/conexões | As três disciplinas continuam disponíveis. |
| CSV UTF-8/BOM, acentos e `001` | Nome e código preservados. Carga de 45h vira 2.700 min usando `Carga horária (h)`. |
| CSV com `Carga (h)` | **Defeito confirmado:** a coluna não é reconhecida; carga fica nula e o valor é transferido para observações. Essa grafia é sugerida pela própria UI. |
| DOCX sintético tabular | Uma disciplina reconhecida, código preservado; o mesmo cabeçalho curto não preserva carga como campo. |
| PDF textual sintético, estrutura UCFC | Uma disciplina reconhecida, 60h; sem alegação de extração de documento real ou OCR. |
| PDF válido sem texto | HTTP 400, mensagem genérica de nenhuma disciplina identificada. Falta aviso específico sobre ausência de texto interpretável. |
| CSV vazio / XLSX inválido / arquivo >5 MB | HTTP 400, sem escrita; mensagens de validação. |
| PDF inválido / DOCX inválido | **Defeito confirmado:** HTTP 500; exceções de parser não convertidas em erro de domínio/validação. |
| Arquivo `.tsv` | HTTP 400, formato não suportado, embora o seletor da interface anuncie TSV. Colagem TSV é coberta pela suíte existente. |

A suíte existente também exercitou seleção parcial, confirmação obrigatória, rollback de lote inválido, duplicado normalizado, atualização explícita e escolha entre várias planilhas. Os testes correspondentes passaram.

Não foi fornecida nesta solicitação uma grade pessoal real. Os dois testes de PDFs reais foram pulados porque os arquivos esperados não estão disponíveis. Não é possível atribuir a falha original do arquivo do usuário exclusivamente à seleção sem esse arquivo. O parser PDF atual reconhece layouts específicos (UCFC/cronograma); não é um extrator genérico de qualquer grade.

## 5. Reprodução no navegador e persistência

Edge 155.0.4283.45, Playwright headless, 1440×1000 e inspeção adicional em 390×844. A habilidade de controle desktop foi consultada, mas sua ferramenta `node_repl` não estava exposta; foi usado Playwright pré-instalado. Servidor de teste com bind `127.0.0.1`, porta **5053**, debug desligado, SQLite próprio. Não houve publicação.

Fluxo efetivamente executado pela UI:

1. Formações vazias abre sem erro de JavaScript; botão Nova formação disponível.
2. Criar um curso sintético pela UI, abrir Grade curricular, escolher o XLSX oficial e gerar a prévia.
3. Conferir três linhas e nenhuma selecionada. Ao confirmar, aparece “Selecione ao menos uma linha para confirmar a importação”; nenhuma chamada POST de confirmação nessa tentativa.
4. Marcar somente a primeira linha, confirmar e recarregar. Uma disciplina persistida, confirmada também pelo GET da API.
5. Encerrar o processo de teste, iniciar novamente com o mesmo SQLite e consultar: a disciplina continua presente.
6. Abrir Hoje, Foco, Histórico e Análises. Todas abriram, com HTTP 200 nas APIs observadas. Após a importação, Foco diz **“Não há matérias disponíveis”**: evidência direta da etapa separada `materias_estudo`.

`GET /api/diagnostics` da instância testada apontou exatamente para o `browser.db` isolado. Não havia instância pessoal previamente aberta a comparar. O banco pessoal foi inspecionado separadamente em modo leitura.

Não houve exceção JS no fluxo completo. A sondagem inicial registrou dois 404 de `/favicon.ico`, sem relação com importação. A prévia possui conteúdo horizontal cortado na captura desktop; merece simplificação de layout. Hoje mobile abre, mas apresenta muitos cartões de planejamento. A captura da prévia contém um toast “Alteração salva” ainda relativo à criação anterior do curso; a grade continuava sem escrita.

Capturas: `ui-empty-formations.png`, `ui-preview-unselected.png`, `ui-import-persisted.png`, `ui-today-mobile.png`. Rede e passos: `ui_evidence.json`; conferência após reinício: `final_checks.json`.

O relógio foi aberto em estado sem estudos disponíveis. Não foi feito ciclo completo de cronômetro pela UI nesta fase; persistência, exclusividade de foco e finalização idempotente foram exercitadas pelos testes existentes. Não houve homologação completa por teclado, correções, CSV, restauração ou reinício da máquina.

## 6. Baseline e resultados dos testes

- Python: 44 arquivos (incluindo testes, excluindo docs, `.venv` e caches). JavaScript: 5 arquivos.
- `services/core.py`: 7.130 linhas, 419.035 bytes.
- `static/js/app.js`: 4.358 linhas, 428.590 bytes; continua carregado inteiro em Hoje.
- `static/js/focus.js`: 853 linhas, 44.027 bytes.
- `services/grade_import.py`: 576 linhas, 25.988 bytes.
- `routes/api.py`: 513 linhas; 126 declarações de endpoint. Aplicação completa: 144 regras Flask, incluindo páginas, calendário e estáticos (não são 144 casos de uso de API).
- Cinco dependências diretas instaladas: Flask 3.1.3, python-docx 1.2.0, pypdf 6.20.0, openpyxl 3.1.5, tzdata 2026.5. Python do ambiente criado: 3.12.
- Migrations em banco novo: 81,39 ms. Inicialização de processo + import de `app.py` + banco NOVO isolado: 390,29 ms (uma amostra). Importar `app.py` só ocorreu nesse processo com `PLANO_DATABASE_PATH` explicitamente temporário.
- UI, uma navegação por rota em máquina local com zero sessões: Hoje 64 ms; Foco 40 ms; Histórico 48 ms; Análises 131 ms. Medição até renderização observada, com recursos parcialmente em cache; não é benchmark estatístico nem comparação V2/V3.
- Não há evidência de lentidão com 1.000/10.000 sessões nesta fase. O volume de código mostra custo de manutenção, não prova consumo excessivo de CPU. Hoje depende de três chamadas; Análises de seis. Medir consultas/índices em volume pertence às etapas posteriores.

Comando da suíte: `& .\.venv\Scripts\python.exe -m unittest discover -s tests -v` (com `PLANO_DATABASE_PATH` isolado conforme comandos abaixo).

**151 testes executados em 21,137 s: 146 aprovados, 3 falhas, 2 pulados.** Log integral: `baseline_tests.log`.

Falhas observadas, sem modificação dos testes:

1. `test_adaptive_focus_calendar_stage...test_three_consistent_observations_adjust_once_and_decision_is_idempotent`: `[False, False, False]` em vez de `[False, False, True]`.
2. `test_interactive_planning_api...test_analytics_exposes_daily_reason_coverage_and_budget_history`: histórico de orçamento não contém o estudo esperado.
3. `test_master_spec_completion...test_deadline_check_is_once_and_prepared_does_not_add_budget`: `deadline_check_due=False`.

Esses casos usam datas fixas de setembro/2026 enquanto a execução foi em outubro. Sensibilidade à data atual é uma hipótese forte, não uma causa isolada comprovada por este trabalho. São testes do legado de planejamento/recomendação; não serão critérios funcionais da V3 removida, mas suas falhas permanecem registradas.

## 7. Plano mínimo para Fase 1 — ainda não executado

Proposta: criar `a/plano_v3` como aplicação independente, preservando `a/plano_v2` e seu banco. Mesmo Flask/Jinja/JS/SQLite; evitar dependências novas.

| Destino proposto | Decisão |
|---|---|
| `config.py`, `database/connection.py`, migrations novas | Caminho V3 explícito fora do OneDrive, integridade, FK, transações e erros de configuração. Nunca descobrir/importar automaticamente o banco V2. |
| Cursos/disciplinas, serviços e APIs próprios | `courses` e `subjects`, arquivo/edição sem apagar histórico; deduplicação por curso. Mesmos nomes em dois cursos continuam independentes. |
| Parser de grade isolado | Reaproveitar normalização/extratores testados; corrigir aliases de carga, tratamento de arquivos inválidos e mensagem de PDF sem texto; alinhar formatos aceitos com a UI. Sem importar `core.py`. |
| UI Disciplinas + módulos JS por página | Prévia editável, seleção em lote e contagens claras; confirmação transacional. Fluxo de estudar diretamente a disciplina importada, sem cadastro de metas/estudo atual. |
| Timer | Reimplementar serviço pequeno a partir dos contratos de tempo líquido, versão, pausas, recuperação e finish idempotente. A Fase 1 precisa incluir integração mínima persistida para “Estudar agora”; cobertura completa fica na Fase 2. |
| Histórico/análises | Reimplementar na Fase 3 com uma fonte de segundos efetivos, rateio no fuso, paginação SQL e CSV usando os mesmos filtros; exatamente dois gráficos. Não reutilizar `history()` limitado ou `analytics_workload()` misto. |
| Legado | Preservar V2 no diretório e Git; manter planejamento, Google, avaliações, campanhas e projetos fora dos imports/rotas/clientes da V3. Não apenas ocultar itens por CSS. |

Modelo proposto é o do roteiro: cursos, disciplinas, sessões, pausas, timer persistido, correções e migrations. Definir intervalos de foco em instantes absolutos para repartir corretamente sessões e pausas na meia-noite local; a soma dos dias deve ser exatamente o tempo líquido. Sessão manual sem horários terá data local e duração explícita.

O banco fornecido não contém histórico para migrar. Se aparecer uma cópia com dados, suspender importação automática e projetar mapeamento de IDs/curso/disciplinas/pausas/notas em uma cópia, com reconciliação antes/depois. Não alegar recuperação de histórico.

Critérios de conclusão da Fase 1: dois cursos, grades homônimas independentes, prévia sem escrita, importação repetida sem duplicação, persistência após reinício, disciplina importada inicia foco diretamente, integridade e versões validadas. Não expandir para as demais fases no mesmo passo.

## 8. Alterações efetivas, execução e pendências

Criados `docs/v3/FASE_0_DIAGNOSTICO.md`, scripts de auditoria/servidor/UI, evidências JSON, logs e quatro capturas. Alterado somente `.gitignore` entre os arquivos já rastreados. Ambiente `.venv` recriado e ignorado. Nenhum arquivo funcional Python/JS/CSS/template, migration ou requisito foi alterado nesta fase. Backups e bancos de teste ficam fora do repositório.

Reexecutar a partir de `a/plano_v2` no PowerShell (o primeiro comando cria uma nova pasta isolada e novo backup):

```powershell
& .\.venv\Scripts\python.exe docs\v3\audit_phase0.py
$evidence = Get-Content docs\v3\evidence.json -Raw | ConvertFrom-Json
$env:PLANO_DATABASE_PATH = Join-Path $evidence.workdir 'baseline-suite.db'
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
Remove-Item Env:PLANO_DATABASE_PATH
& .\.venv\Scripts\python.exe docs\v3\serve_phase0.py (Join-Path $evidence.workdir 'browser.db')
# Em outro terminal, com o servidor de auditoria ativo e browser.db novo:
node docs\v3\probe_ui.cjs
node docs\v3\audit_ui.cjs
```

Os scripts JS usam o Playwright do runtime local Codex indicado no próprio arquivo, não uma dependência nova do produto. `serve_phase0.py` rejeita bancos fora da pasta de auditoria. A UI de teste cria somente dados sintéticos no `browser.db`; para repetir do zero, execute nova auditoria em vez de apagar um banco existente. O servidor temporário foi encerrado ao fim da auditoria.

Limitações restantes: grade pessoal real indisponível; sem teste de OCR, carga elevada, todas as ações de teclado/mobile, restauração ou reinício do Windows. Não foram procurados backups remotos para recuperação de dados. Essas limitações não foram marcadas como aprovação.

**Próximo passo:** autorização para Fase 1. O documento fornecido determina: “Sem mudanças de comportamento. Pare e peça aprovação para a Fase 1.” A etapa preparatória acima está concluída; nenhuma refatoração funcional foi iniciada.
