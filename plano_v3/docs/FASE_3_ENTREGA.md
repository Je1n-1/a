# Fase 3 — análises, histórico e exportação

Concluída em 10/10/2026. Atualização aplicada ao site local na porta 5054. O curso de teste foi excluído conforme autorização explícita do usuário.

## 1. Diagnóstico factual

A Fase 2 já persistia sessões, intervalos UTC, pausas e recuperação. `tracker/sessions.py` calculava a divisão diária de uma sessão, mas Análises era uma tela de etapa futura. Não havia consulta do histórico completo, CSV nem correção auditável de registros concluídos.

Foram consultados `tracker/sessions.py`, `timer.py`, `db.py`, `http.py`, `catalog.py`, `upgrade.py`, os templates e as regras da Fase 3 do plano fornecido. O histórico recente limitado a cinco registros não foi reutilizado como fonte dos totais. Nenhum cálculo de planejamento da V2 foi trazido para as análises.

O único curso pessoal encontrado tinha ID 1 e nome `.`. Havia zero disciplinas, timers e sessões. Antes de excluir, foi feita cópia consistente e novamente conferida a identidade e a ausência de vínculos dentro da transação. Somente esse cadastro foi removido (`phase3-course-removal.json`).

## 2. Plano mínimo

Adicionar uma projeção diária derivada das sessões/intervalos, atualizada na mesma transação das gravações. Essa projeção permite somas e paginação em SQL, sem carregar todos os registros no navegador ou consultar intervalos individualmente para cada linha do histórico. Usar a mesma seleção de datas/curso/disciplina nos indicadores do período, gráficos, tabela e CSV.

Adicionar versionamento e trilha de correções com motivo, antes/depois e chave idempotente. Manter pausas/intervalos originais ao editar somente dados descritivos e explicitar quando o usuário substitui o tempo por uma duração ou novos horários.

## 3. Mudanças efetivamente feitas

| Arquivos | Resultado |
| --- | --- |
| `migrations/0003_analytics.sql` e `.py` | Duas tabelas (`session_days`, `session_corrections`), versão/forma do tempo na sessão e preenchimento dos registros existentes. O checksum inclui SQL e Python. |
| `tracker/db.py` | Execução transacional do preenchimento da migration e conferência da reconciliação entre rateio e sessões no diagnóstico. Migrations anteriores não foram editadas. |
| `tracker/sessions.py`, `tracker/timer.py` | Atualização da projeção diária junto com registro manual e finalização. Correções conservam os intervalos originais para referência. |
| `tracker/analytics.py` | Filtros parametrizados, totais, dois agrupamentos, paginação SQL e CSV integral. Resumo curto para Hoje sem carregar gráficos. |
| `tracker/corrections.py` | Edição com motivo, antes/depois, versões e reenvio idempotente; rejeição de conflito entre abas. |
| `tracker/http.py` | Endpoints de análises, CSV, resumo de Hoje, correção e consulta da auditoria. |
| `templates/analytics.html`, `static/css/analytics.css`, `static/js/analytics.js` | Tela final de análises: quatro indicadores, exatamente dois gráficos, filtros, tabela e paginação. CSS/JS carregados somente nessa página. |
| `static/js/session-editor.js`, `study-format.js`, `templates/base.html` | Formulário de correção, auditoria legível, formatação exata e bloco de estilos por página. |
| `templates/today.html`, `static/js/today.js`, `static/css/app.css` | Tempo concluído de hoje/semana junto ao relógio, usando a mesma fonte das análises. |
| `tests/`, `docs/`, `README.md` | Testes de reconciliação e migração, roteiro de navegador, CSV sintético e instruções. |

Nenhum arquivo funcional nem banco da V2 foi alterado. Sem novas dependências, commit, push ou publicação externa. Planejamento permanece fora do código ativo da V3.

## 4. Segurança e dados

Banco pessoal ativo:

```text
C:\Users\jeanm\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\PlanoV3\data\plano.db
```

Backups, no diretório `PlanoV3\backups`, fora do banco ativo e do OneDrive:

- `before-test-course-removal-20261010-143601.db`: contém o curso de teste antes da exclusão autorizada.
- `before-upgrade-20261010-144642-770198.db`: banco imediatamente antes da Fase 3.
- `verified-upgrade-20261010-144642-770198.db`: cópia em que a atualização foi ensaiada e validada antes de aplicar ao original.

O esquema passou de `0001_tracker` + `0002_timer_recovery` para incluir `0003_analytics`. O servidor foi parado durante a atualização. O script comparou todas as linhas/colunas preexistentes e confirmou integridade `ok` e zero violações FK. O relatório está em `phase3-upgrade-result.json`.

A base pessoal permaneceu sem cursos e sem sessões depois de remover o cadastro de teste. Não recebeu os 124 registros artificiais usados no navegador, que ficam exclusivamente em `PlanoV3\verification\phase3\analytics-browser.db`.

## 5. Testes executados

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q app.py backup.py upgrade.py tracker migrations tests
Get-ChildItem static/js/*.js | ForEach-Object { node --check $_.FullName }
node tests/browser_phase3.cjs
```

**40 testes automatizados aprovados**, sem falhas nem testes ignorados (`phase3-tests.log`), incluindo os 30 contratos anteriores. A consulta rápida adicionada a Hoje também teve seu teste específico reexecutado após a inclusão dos indicadores.

Os dez testes da Fase 3 cobrem:

- Estado vazio, dias zerados, parâmetros/datas inválidos, limites de período e data máxima aceita pelo tipo Python.
- 123 registros, sete páginas e exportação sem truncar em 100 nem na página aberta.
- Cursos/disciplinas homônimos, estudo avulso, itens arquivados e escopo explícito dos cards hoje/semana/mês.
- Sessão com pausa atravessando meia-noite e filtro parcial: tabela, CSV, gráfico diário, gráfico por disciplina e total do período coincidem, preservando segundos.
- Correção com motivo e versão, antes/depois auditáveis, reenvio sem duplicação, conflito de versão e atualização do rateio de todas as saídas.
- Correção só da nota preservando pausas; substituição por horários transferindo os totais para as datas/curso escolhidos.
- Validação e rollback de correção inválida, sem aplicar parte das mudanças.
- CSV com BOM, ponto e vírgula, acentos, aspas, quebra de linha, segundos inteiros e campos que poderiam iniciar fórmulas neutralizados.
- Quantidade constante de consultas: sete SELECTs para relatório completo; histórico usa `LIMIT/OFFSET` no SQLite, sem consultas por sessão.
- Migração de sessão antiga atravessando meia-noite; interrupção do ensaio quando os totais antigos não conferem; hash do arquivo de origem preservado nessa falha; recusa de iniciar com rateio inconsistente.

As validações desta fase passaram na primeira execução; não houve falha funcional a ocultar. Os avisos de pypdf no log correspondem à amostra propositalmente inválida testada na Fase 1.

## 6. Verificação visual e operacional

Roteiro no Edge com 124 sessões sintéticas: dois gráficos, filtros, segunda página mantendo os totais, download com 124 linhas de dados, filtro de um único dia mostrando apenas dez minutos da sessão noturna, correção para 25 minutos e 7 segundos e auditoria com os valores anteriores. Sem erro JavaScript nem HTTP (`phase3-ui.json`).

Capturas desktop e móvel de 390 px foram abertas e inspecionadas. A página não apresentou transbordamento horizontal; os gráficos/tabela usam rolagem interna quando necessário. O botão de salvar a correção permanece dentro da viewport. Evidências: `phase3-analytics-overview.png`, `phase3-analytics-desktop.png`, `phase3-analytics-mobile.png`, `phase3-correction-mobile.png`, `phase3-audit.png` e `phase3-empty.png`.

Os indicadores de Hoje foram comparados no navegador com os de Análises e coincidiram (`phase3-today-ui.json`). Na base pessoal, a tela foi aberta após atualizar: dois gráficos em estado vazio, total zero, nenhum curso e nenhuma falha JS (`phase3-live-verification.json`). O servidor pessoal permanece ligado na porta 5054; o servidor de testes é encerrado.

O CSV foi baixado no navegador e interpretado pelos testes, incluindo acentos e valores exatos. Não foi aberto no aplicativo Excel instalado; não há alegação dessa verificação visual específica.

## 7. Medições e regras de reconciliação

Métricas em `phase3-metrics.json`: nove tabelas, sete SELECTs por relatório completo, consultas agregadas constantes independentemente da quantidade de sessões e zero novas dependências. Bytes JavaScript, arquivos e rotas foram contados nesse arquivo. Não foi realizado benchmark de CPU/memória/latência.

Para o mesmo período/curso/disciplina, a soma líquida de todas as páginas do histórico coincide com o card do período, os dois gráficos e o CSV. A fonte comum é `session_days`, derivada de intervalos UTC e repartida em dias de São Paulo. Uma sessão pode contribuir parcialmente em filtros de data; os campos `total_effective_seconds`/`total_break_seconds` conservam a referência da sessão inteira e a interface sinaliza a parcela filtrada.

Hoje, semana e mês respeitam curso/disciplina, mas usam seus próprios intervalos de data. A semana começa na segunda-feira; mês e semana vão até hoje. Esses cards não são parcelas para somar entre si. Sessões em andamento/canceladas e planejamento não entram nos totais.

## 8. Limites e próxima etapa

Consulta limitada a 3.661 dias por vez; gráficos exibem minutos arredondados a duas casas, enquanto persistência, CSV e reconciliação usam segundos inteiros. Cada sessão corrigida continua sendo uma única linha histórica e preserva sua origem (cronômetro/manual).

Ao substituir o tempo por duração ou novos horários, as pausas do resultado corrigido são zeradas e a UI informa essa escolha; a trilha mantém os valores anteriores. Alterar só nota/disciplina conserva horários e pausas. A edição individual de cada intervalo de uma sessão concluída não foi implementada.

As próximas etapas do plano são revisão de manutenção/desempenho e homologação final, incluindo backup/restauração pela interface e verificação em outra instalação Windows. Ainda não há restauração pela interface nem data do último backup no diagnóstico. Não foi realizado reinício físico do computador.
