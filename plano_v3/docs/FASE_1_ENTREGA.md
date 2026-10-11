# Entrega da Fase 1 — 10/10/2026

## 1. Diagnóstico factual

Base usada: `a/plano_v2`, na branch `refactor/study-tracker-v3`. A auditoria anterior está em `../plano_v2/docs/v3/FASE_0_DIAGNOSTICO.md`. O banco V2 tem esquema íntegro, mas não contém cursos, disciplinas nem sessões pessoais; não houve recuperação de histórico.

O importador V2 reconhece três linhas no modelo e as deixa desmarcadas. A confirmação ignora linhas não selecionadas. Além dessa dificuldade de seleção, a V2 exige converter `disciplinas_grade` em `materias_estudo` antes de iniciar o relógio. O parser também não reconhecia o cabeçalho `Carga (h)` em uma das formas normalizadas, anunciava TSV sem aceitar a extensão e deixava erros de PDF/DOCX inválidos escaparem como falha de servidor.

Foram consultados o diagnóstico anterior, `services/grade_import.py`, modelo XLSX e contratos de cursos, importação e foco. Não foi fornecida uma grade pessoal para reproduzir um eventual erro específico dela. Os resultados desta entrega se referem ao modelo oficial e às amostras descritas abaixo.

## 2. Plano mínimo e impacto nos dados

A V3 foi isolada em `a/plano_v3`, com banco novo explicitamente escolhido fora do OneDrive. O parser foi reaproveitado isoladamente; catálogo, HTTP, persistência e cronômetro mínimo foram separados. A disciplina importada é a própria referência do timer, dispensando uma segunda entidade de planejamento.

O esquema `0001_tracker` contém seis tabelas: `v3_migrations`, `courses`, `subjects`, `timers`, `timer_intervals` e `study_sessions`. Intervalos guardam foco e pausas em UTC. O índice de timer ativo impede duas sessões simultâneas; a sessão histórica possui vínculo único com o timer. Correções auditáveis e campos necessários às etapas posteriores serão acrescentados em novas migrations, sem editar a versão aplicada.

## 3. Mudanças efetivamente realizadas

| Arquivos | Mudança e finalidade |
| --- | --- |
| `app.py`, `tracker/db.py`, `migrations/0001_tracker.sql` | Inicialização explícita, validação do esquema/checksums, integridade, FK e transações; servidor local na porta 5054. |
| `tracker/catalog.py`, `tracker/domain.py` | Cadastro, edição, arquivamento/restauração e validação de cursos/disciplinas; duplicidade normalizada por curso. |
| `tracker/imports.py`, `tracker/grade_parser.py` | Prévia sem escrita, seleção/edição, abas XLSX, confirmação atômica, duplicados ignorados ou atualizados por escolha explícita; ajustes TSV, cabeçalhos e erros de arquivo. |
| `tracker/timer.py`, `tracker/http.py` | Início direto/avulso, pausa, retomada, conclusão idempotente, cancelamento e cinco sessões recentes; API independente de planejamento. |
| `templates/`, `static/css/app.css`, `static/js/` | Hoje, Disciplinas e Análises; relógio circular, importação com contagens claras, edição e layout móvel. Análises informa que será desenvolvida na próxima etapa. |
| `static/downloads/modelo_grade_curricular.xlsx` | Modelo existente reaproveitado. |
| `setup.ps1`, `run.ps1`, `requirements.txt`, `.gitignore`, `backup.py` | Instalação/execução Windows, mesmas dependências funcionais, exclusão de dados e ambiente virtual do Git e backup SQLite explícito. |
| `tests/`, `docs/`, `README.md` | Contratos automatizados, roteiro de navegador, evidências e instruções. |

Todos esses arquivos foram criados na V3. Nenhum arquivo funcional da V2 foi modificado ou removido nesta fase. A alteração em `plano_v2/.gitignore` e a documentação V2 que já constavam no Git pertencem à Fase 0. Não houve commit, push ou publicação.

## 4. Segurança e localização dos dados

Banco V3 pessoal, inicializado vazio, esquema `0001_tracker`:

```text
C:\Users\jeanm\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\PlanoV3\data\plano.db
```

O caminho físico decorre do redirecionamento de `%LOCALAPPDATA%` neste ambiente Windows. Ele consta explicitamente em `config.local.json`, ignorado pelo Git. Há zero cursos, disciplinas, timers, intervalos e sessões pessoais. O diagnóstico retorna integridade `ok` e zero violações FK. Não há descoberta automática ou conversão do banco V2.

Backup consistente da V2 criado na Fase 0:

```text
C:\Users\jeanm\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\Plano\backups\plano-v2-before-v3-20261010-110837.db
```

O SHA-256 do banco V2 permaneceu `64d27a914070a2abe783001162ca2f4bdbb8b8dc4319f930ab0c4bdd984602a6`. Seu esquema permanece com 15 migrations e 42 tabelas.

Os registros de teste ficam em `PlanoV3\verification\20261010-112700\browser.db`, no mesmo diretório local resolvido do Windows, fora do banco pessoal. O backup dessa base em uso, `backup-validation.db`, foi validado com integridade e contagens iguais para todas as tabelas. Isso não representa restauração ou migração dos dados pessoais. O campo “último backup” ainda não é registrado no diagnóstico.

## 5. Testes e resultados

Comandos executados na pasta V3:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q app.py backup.py tracker tests
Get-ChildItem static/js/*.js | ForEach-Object { node --check $_.FullName }
node tests/browser_phase1.cjs
.\run.ps1
```

Resultado final: **15 testes Python aprovados**, sem falhas nem testes ignorados; compilação Python e sintaxe dos cinco arquivos JS aprovadas. O log está em `phase1-tests.log`. A amostra de PDF propositalmente inválida pode imprimir avisos do pypdf; o teste confirma resposta HTTP 400 com mensagem útil.

Cobertura executada: inicialização idempotente; recusa de banco ausente/legado/esquema incompleto/checksum alterado; modelo XLSX com zero seleção e prévia sem gravação; seleção e confirmação; CSV/TSV/TXT/colagem com acentos e código `001`; múltiplas abas; DOCX tabular e PDF textual sintéticos; arquivos vazios, grandes, inválidos e PDF sem texto; duplicados por curso; atualização explícita; rollback de lote inválido; edição/arquivamento/restauração; início direto; estado após recriar o aplicativo; somente um timer ativo; versões antigas com 409; conclusão repetida sem duplicar histórico; cancelamento; proteção de origem/host local.

Com relógio simulado, 10 minutos de estudo + 5 de pausa + 20 de estudo produziram 1.800 segundos líquidos e 300 segundos de pausa. Arquivar o curso conservou a sessão.

Durante a primeira execução, conexões SQLite não fechadas mantiveram arquivos temporários presos no Windows. Os contextos foram corrigidos para fechar explicitamente as conexões; a execução final passou sem esse problema.

Não executados nesta fase: reinício do Windows, grade pessoal real, recuperação de duração longa, rateio diário na madrugada, registro manual, trilha de correções, histórico paginado, reconciliação analítica e CSV. Não são apresentados como aprovados.

## 6. Verificação visual e operacional

Edge com Playwright: duas formações, cinco disciplinas no total, homônimas mantidas separadas; modelo com três identificadas/zero selecionadas; seleção em lote e correção da carga; reimportação sem duplicar; início em um clique; recarga e segunda aba recuperando o timer; pausa, retomada e conclusão com nota. Sem erro JavaScript nem resposta HTTP de erro no roteiro (`phase1-ui.json`).

Inspeção em desktop e largura de 390 px, incluindo importador. A tabela da prévia pode rolar internamente no celular; a página não apresentou transbordamento horizontal. Capturas `phase1-subjects.png`, `phase1-timer.png` e `phase1-mobile-import.png` foram abertas e inspecionadas visualmente; demais capturas constam na mesma pasta.

O servidor foi realmente parado e reiniciado com a base de verificação: as cinco disciplinas e o mesmo timer pausado persistiram, com tempo líquido inalterado (`restart-result.json`). O timer de teste foi cancelado depois da conferência.

O lançador `run.ps1` foi executado com a configuração pessoal: página inicial HTTP 200, diagnóstico íntegro, nenhum curso e nenhum timer ativo (`run-script-verification.json`). Os processos usados na verificação são encerrados ao finalizar a entrega; o usuário inicia sua instância com `run.ps1`.

## 7. Medições

Nesta etapa: 10 arquivos Python de produto, cinco arquivos JS somando 27.123 bytes, 20 regras Flask (15 de API) e seis tabelas. Medições em `phase1-metrics.json`. O `app.js` da V2, sozinho, possui 428.590 bytes; essa comparação indica menor volume de código ativo, não prova ganho de velocidade e não compara produtos com todas as mesmas funcionalidades.

Não foi realizado benchmark de carregamento, memória ou CPU. Os módulos de Hoje não carregam gráficos nem planejamento. Mantidas as dependências Flask, python-docx, pypdf, openpyxl e tzdata, sem React, ORM, Redis ou fila de tarefas.

## 8. Pendências e próximo passo

Os critérios funcionais da Fase 1 foram atendidos. O cronômetro implementado aqui permite usar a disciplina importada e registrar uma sessão básica, mas ainda requer os contratos completos e a homologação da Fase 2. O próximo passo é recuperação de sessões longas/interrompidas, comportamento de concorrência, rateio no fuso America/Sao_Paulo e demais cenários de histórico-base. Indicadores, dois gráficos, filtros, paginação, correções auditáveis e CSV pertencem à etapa de análises.

Análises permanece uma tela de etapa futura. Não há gráfico ou indicador fictício. A data local atualmente gravada na sessão é a do início; intervalos UTC são conservados para o futuro rateio correto, e nenhum total diário é apresentado como se esse rateio já existisse.

O documento fornecido pede “Trabalhe apenas em uma fase aprovada”. Esta entrega encerra a Fase 1; a próxima fase depende da continuidade autorizada pelo usuário.
