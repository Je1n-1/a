# Fase 4 — manutenção e desempenho

Concluída em 10/10/2026. Código aplicado ao site local na porta 5054, sem alteração de esquema.

## 1. Diagnóstico factual

Foram examinados `app.py`, serviços em `tracker/`, módulos JS, templates, requirements, testes e o plano fornecido. Hoje fazia cinco chamadas ao abrir, consultas após respostas de mutação já completas e duas atualizações no retorno à aba. Análises carregava o editor e o formulário manual mesmo para consultar. O catálogo carregava o importador antes de abrir a importação.

O relatório fazia sete SELECTs, sem consulta por linha, com paginação SQL. O EXPLAIN mostrou o índice existente `session_days_date`; havia joins desnecessários com disciplinas/cursos nas agregações sem filtro de curso. Planejamento, Agenda, campanhas, projetos e previsões já estavam ausentes dos imports e rotas ativos da V3. A V2 permanece no diretório e histórico Git para consulta.

## 2. Plano mínimo

Consolidar a leitura inicial de Hoje em uma transação, retirar consultas redundantes após mutações, carregar formulários sob demanda e simplificar joins sem alterar os filtros. Preservar contratos de importação, idempotência, versões do relógio e projeção diária. Introduzir ferramentas opcionais de formatação/verificação e medir antes/depois. Nenhuma migration necessária.

## 3. Mudanças feitas

- `tracker/today.py` e `tracker/http.py`: serviço tipado e `GET /api/today`; `catalog=0` omite cursos/disciplinas. Endpoints existentes preservados.
- `today.js`: uma chamada inicial, atualização de retorno à aba agrupada, sem GET adicional após sucesso de iniciar/pausar/retomar. Falha de mutação ainda reconcilia o estado persistido. Recuperação de falha inicial recarrega também o catálogo.
- `analytics.js`, `subjects.js`, `manual-session.js`, `session-editor.js`, `study-format.js`: importação dinâmica dos formulários e função de horário compartilhada, sem dependência do formulário manual para corrigir sessões.
- `analytics.py`: joins de catálogo apenas quando necessários para filtros ou nomes. Mantidos sete SELECTs e os índices existentes; nenhuma tabela removida.
- Python de produto/testes/scripts e JavaScript de produto formatados; imports sem uso removidos pelo Ruff. `app.py` deixou de incluir o caminho pessoal do banco no log informativo.
- `requirements-dev.txt`, `pyproject.toml`, `scripts/check.py`, `.gitignore`, README, benchmark e testes: rotina de manutenção reproduzível. Migrations excluídas da formatação.

Não houve commit, push ou publicação. Dependências de execução permanecem as mesmas cinco da V2 e das fases anteriores: todas atendem funções preservadas. A redução ocorreu nas rotas e dependências entre módulos; não se alega redução da quantidade de pacotes externos.

## 4. Dados e reversibilidade

O banco pessoal continua no caminho configurado em `config.local.json`, fora do OneDrive, sob `PlanoV3/data/plano.db` no diretório local resolvido pelo Windows. Backups anteriores permanecem em `PlanoV3/backups`; esta fase não fez migração nem escrita de teste nele. Diagnóstico: integridade `ok`, zero violações de chave estrangeira, versões `0001_tracker`, `0002_timer_recovery`, `0003_analytics`.

Durante o desenvolvimento, uma cópia do código da Fase 3 manteve o site pessoal disponível. Essa cópia permanece em `PlanoV3/verification/phase4/phase3-server`, utilizável com o mesmo esquema. As migrations foram comparadas byte a byte com ela e são idênticas. O banco V2 manteve SHA256 `64d27a914070a2abe783001162ca2f4bdbb8b8dc4319f930ab0c4bdd984602a6`.

Testes de navegador e benchmark usam bases sintéticas em `PlanoV3/verification`, separadas do banco pessoal. Caminhos locais completos e checksums estão nas evidências `phase4-environment.json` e `phase4-metrics.json`.

## 5. Testes executados

```powershell
.\.venv\Scripts\python.exe scripts/check.py --fix
.\.venv\Scripts\python.exe scripts/check.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
$env:PLANO_TEST_ENVIRONMENT = 'docs/phase4-environment.json'
$env:PLANO_TEST_EVIDENCE = 'docs/phase4-clock'
node tests/browser_phase2.cjs
node tests/browser_phase4.cjs
```

41 testes passaram, incluindo os contratos anteriores de importação, timer, concorrência, recuperação, interrupção de processo, correções, rateio, CSV e paginação, além da equivalência do novo endpoint com as APIs anteriores. Evidência: `phase4-tests.log`.

Ruff e sintaxe JS aprovados. Na preparação, a primeira execução encontrou comandos Python na mesma linha; a formatação os corrigiu. Uma segunda passagem de formatação foi necessária em `today.js`. As verificações finais passaram. Nenhuma falha de teste funcional foi ocultada.

## 6. Navegador e operação

Edge executou perda de resposta de pausa, duas finalizações concorrentes sem duplicar, reenvio manual, meia-noite, recuperação de nove horas, desconexão/reconexão e largura de 390 px. O roteiro adicional confirmou uma chamada inicial de Hoje, agrupamento de eventos de retorno, ausência de GET após pausa, formulário XLSX sob demanda, zero selecionadas na prévia, reimportação sem duplicar e correção com auditoria. Sem erros JavaScript nesses roteiros.

Captura móvel de Análises aberta e inspecionada: dois gráficos e tabela com rolagem interna, sem transbordamento da página. Evidências: `phase4-clock-ui.json`, `phase4-ui.json`, `phase4-analytics-mobile.png` e capturas `phase4-clock-*`. Testes não executados nesta fase: reinício do Windows, grade pessoal real e abertura do CSV no Excel.

O servidor de teste foi encerrado após validação. O servidor pessoal permanece em `http://127.0.0.1:5054`, ligado apenas no endereço local, sem debug.

## 7. Medições antes/depois

Mesmas bases sintéticas; Python 3.12.14 e Edge. Medianas de nove execuções de consulta, cinco inicializações em processos novos e cinco contextos novos de navegador por tela. A inicialização mede importação e `create_app`, sem tempo de criação do processo. Medidas locais, sem isolamento do restante da atividade do computador; parte da medição posterior coincidiu com a regressão do navegador. Não representam um ensaio de carga ou garantia de latência.

| Sessões | Inicialização (ms) | Consulta 30 dias (ms) | Consulta 365 dias (ms) | Hoje pronto (ms) | Análises pronta (ms) |
| --- | --- | --- | --- | --- | --- |
| 0 | 170,137 → 194,057 | 0,742 → 0,729 | 0,948 → 0,942 | 102 → 102 | 98 → 97 |
| 1.000 | 173,024 → 198,751 | 1,149 → 1,207 | 3,449 → 3,147 | 111 → 99 | 103 → 104 |
| 10.000 | 192,414 → 213,645 | 3,339 → 3,223 | 28,956 → 25,196 | 109 → 100 | 105 → 107 |

Hoje: **5 → 1 chamadas API**, **5 → 4 módulos JS**. Análises: três chamadas preservadas, **6 → 4 módulos**, **18.848 → 13.864 bytes JS** (26,4% menos). A formatação legível aumentou o JS inicial de Hoje de 16.828 para 17.391 bytes (3,3%); não houve minificação. A inicialização piorou cerca de 21–26 ms; não se afirma ganho geral de velocidade.

O relatório anual com 10 mil sessões passou de 28,956 para 25,196 ms (13% nesta execução). O EXPLAIN retirou as buscas de catálogo do agrupamento interno sem filtro de curso, mantendo o índice por data e os joins finais para nomes. Não houve evidência suficiente para novo índice.

A V3 tem 28 regras Flask (23 API), contra 144 regras na V2 auditada. São nove arquivos JS, somando 52.555 bytes, contra 428.590 bytes apenas no antigo `app.js`. Essa diferença reflete também o escopo menor. Em relação à Fase 3, o total JS cresceu de 46.006 bytes devido à formatação e tratamento de carregamento; a redução relevante desta fase está no que cada tela carrega e nas chamadas feitas.

Arquivos completos: `phase4-benchmark-before.json`, `phase4-benchmark-after.json`, `phase4-metrics.json`. Reprodução:

```powershell
$planoBench = Join-Path $env:LOCALAPPDATA 'PlanoV3\verification\phase4-benchmark'
.\.venv\Scripts\python.exe scripts/benchmark.py --phase before --directory $planoBench
# Aplicar a alteração que se deseja comparar antes do próximo comando.
.\.venv\Scripts\python.exe scripts/benchmark.py --phase after --directory $planoBench
```

## 8. Pendências e próximo passo

Próxima etapa: Fase 5, homologação de instalação limpa, backup/restauração em ambiente separado e relatório final. Permanecem as limitações documentadas de restauração pela interface e data automática do último backup. Não há planejamento ativo nem publicação externa.

A quantidade de dependências externas não foi reduzida, pois as cinco existentes atendem importação, HTTP e fuso necessários. A inicialização não melhorou na medição; isso fica registrado em vez de atribuir ganho a toda a aplicação. O roteiro histórico da Fase 1 ainda espera a tela provisória de Análises; o contrato atual do importador foi executado no roteiro da Fase 4.
