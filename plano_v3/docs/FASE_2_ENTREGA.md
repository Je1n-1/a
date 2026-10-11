# Fase 2 — cronômetro durável e histórico-base

Entrega em 10/10/2026, na continuação autorizada da Fase 1. Aplicada ao site local na porta 5054. A Fase 3 não foi iniciada.

## 1. Diagnóstico factual

Foram consultados `services/core.py` e `static/js/focus.js` da V2, particularmente os contratos de iniciar, pausar, retomar, recuperar e finalizar. A V2 usava oito horas como limite padrão para revisão de sessão longa e conclusão idempotente. Essas garantias foram preservadas na V3 sem carregar planejamento, metas ou o módulo `core.py`.

Na V3 da Fase 1 já havia intervalos persistidos, índice de timer ativo único, versões e sessão histórica única por timer. Faltavam recuperação de período longo, registro manual, rateio por dia e testes de interrupção abrupta/concorrência efetiva. O frontend precisava atualizar sessões recentes após outra aba finalizar e manter explícito o erro quando a resposta de uma ação se perde.

## 2. Plano mínimo

Manter as tabelas e os intervalos existentes; adicionar apenas identificador único para requisições de registro manual e tabela de revisões do timer. Acrescentar serviço de sessões para validar registros e dividir intervalos em datas locais. Preservar a interface do relógio e acrescentar os dois formulários necessários, sem começar o painel de análises.

## 3. Alterações feitas

| Arquivo | Resultado |
| --- | --- |
| `migrations/0002_timer_recovery.sql` | Campo/index de idempotência em `study_sessions` e tabela `timer_recoveries`. A migration 0001 permanece inalterada. |
| `tracker/timer.py` | Revisão obrigatória após oito horas, confirmação total ou horário de parada no trecho aberto, registro dos totais anterior/aceito, pausa após revisão, mensagens de conflito e detecção de relógio do sistema regressivo. |
| `tracker/sessions.py` | Registro manual por data/duração ou início/fim; validação de futuro, limites e fuso; divisão exata por dia; rejeição de horários locais históricos ambíguos/inexistentes sem offset explícito. |
| `tracker/db.py`, `tracker/http.py` | Leituras compostas em uma única transação consistente; endpoints de registro manual e detalhe de sessão. GETs do relógio não modificam o banco. |
| `static/js/today.js`, `static/js/manual-session.js` | Reconexão, atualização entre abas, erro visível, formulários de revisão/manual, origem de sessão e detalhe da divisão diária. O formulário captura o timer/version para não finalizar acidentalmente outra sessão. |
| `templates/today.html`, `static/css/app.css` | Botões novos, aviso de revisão e anel sem limite de sessão; formulário com conteúdo rolável e botão de salvar visível no celular. |
| `upgrade.py` | Backup, ensaio de atualização e comparação dos dados existentes antes de aplicar ao banco escolhido. |
| `tests/test_phase1.py`, novos testes da Fase 2 e `docs/` | Expectativa do novo esquema, testes de concorrência, reinício real, navegador e evidências. |
| `README.md` | Execução, atualização, políticas de tempo, registro manual e limites restantes. |

Nenhum código funcional nem banco da V2 foi alterado. Não houve remoção de dados, commit, push ou publicação externa.

## 4. Dados e atualização

O banco pessoal permaneceu no caminho explícito já configurado:

```text
C:\Users\jeanm\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\PlanoV3\data\plano.db
```

Antes da atualização havia um curso, zero disciplinas, timers, intervalos e sessões. Não havia relógio ativo. Durante o desenvolvimento, a Fase 1 continuou servida a partir de uma cópia do código anterior, conservando o banco pessoal.

Primeiro foi feito um ensaio em cópia (`phase2-migration-copy.json`). Depois, com o servidor parado, `upgrade.py` produziu um novo backup e outra cópia validada antes de aplicar `0002_timer_recovery` ao banco pessoal. Comparou todas as linhas/colunas já existentes, preservando o cadastro; integridade `ok` e zero violações FK após atualizar. Relatório: `phase2-upgrade-result.json`.

Backup imediatamente anterior à atualização:

```text
C:\Users\jeanm\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\PlanoV3\backups\before-upgrade-20261010-141752-560131.db
```

A cópia migrada de verificação fica no mesmo diretório, com nome `verified-upgrade-20261010-141752-560131.db`. Nenhum desses arquivos substituiu o original. Dados sintéticos de navegador permanecem exclusivamente em `PlanoV3\verification\phase2`. Backups e bancos estão fora do Git e do OneDrive. O diagnóstico ainda não armazena a data do último backup.

## 5. Testes executados

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q app.py backup.py upgrade.py tracker tests
Get-ChildItem static/js/*.js | ForEach-Object { node --check $_.FullName }
node tests/browser_phase2.cjs
```

Resultado final: **30 testes aprovados**, sem falhas ou testes ignorados (`phase2-tests.log`); compilação Python e sintaxe dos seis módulos JS aprovadas. Os avisos do pypdf pertencem ao teste proposital de arquivo inválido da Fase 1.

Além dos 15 contratos anteriores, foram executados:

- 10 minutos de foco + 5 de pausa + 20 de foco = 30 minutos líquidos e uma única sessão.
- Pausa atravessando meia-noite: 1.800 segundos de foco + 1.200 de pausa = 3.000 totais, repartidos corretamente entre dois dias.
- Limite exato da meia-noite e mudança histórica de horário de verão em São Paulo, sem perda ou duplicação de segundos.
- Sessão de oito horas exigindo revisão; repetição da revisão idempotente; corte no horário informado preservando trechos fechados e registrando ajuste.
- Revisão inválida, data futura, duração zero/negativa/fracionária, horários incompletos e relógio que retrocede: erro visível sem escrita parcial.
- Duas requisições realmente concorrentes tentando iniciar: uma aceita e outra 409. Duas finalizações concorrentes: mesma sessão histórica. Pausas concorrentes: um intervalo de pausa, sem duplicação.
- Leitura do snapshot enquanto outra conexão pausa: status, versão e intervalo vêm da mesma versão do banco.
- Registro manual com e sem horários, repetição da requisição, homogeneidade de duração/rateio, validação de disciplina arquivada.
- Processo Flask morto abruptamente e reiniciado: mesmo timer ativo, depois mesmo timer pausado; finalização repetida gera uma sessão.
- Processo escritor encerrado antes do commit: gravação incompleta revertida pelo SQLite, integridade preservada.
- Atualização de banco anterior populado: backup do esquema original, comparação das linhas existentes e preservação do total de tempo.

O roteiro de navegador teve duas falhas iniciais de automação: o Edge normalizou um valor de `datetime-local` com segundos zero e uma asserção leu o diálogo anterior antes de terminar o fetch. O roteiro passou após usar a forma normalizada do horário e aguardar o título correto. Essas falhas não foram ocultadas nem tratadas como aprovação.

## 6. Verificação visual e operacional

Edge/Playwright em desktop e 390 px, com capturas abertas e inspecionadas. Em duas abas, ambos os diálogos finalizaram o mesmo timer e só uma sessão foi registrada. Uma resposta de pausa foi perdida depois do commit: a UI mostrou erro e recuperou o estado pausado. Registro manual com resposta perdida foi repetido sem duplicar. Desconectar/reconectar o navegador mostrou estado de conexão e não iniciou outra sessão.

O formulário móvel inicialmente deixava o rodapé fora da área visível; foi ajustado para rolar somente o conteúdo, mantendo Cancelar/Salvar visíveis. Nova conferência automatizada mediu o botão dentro da viewport. Captura final: `phase2-mobile-manual.png`. Outros exemplos: `phase2-recovery.png`, `phase2-daily-allocation.png`, `phase2-mobile-today.png`. Evidência funcional: `phase2-ui.json`.

A instância pessoal foi reiniciada em `http://127.0.0.1:5054`, usando `run.ps1`. Verificação somente de leitura: HTTP 200, esquema com as duas migrations, integridade `ok`, curso conservado e botão de registro manual visível; sem erro JavaScript (`phase2-live-verification.json`). Nenhuma sessão de teste foi criada nessa base. O servidor pessoal permanece ligado conforme solicitado pelo usuário; o servidor separado de testes é encerrado.

## 7. Medições e regras de tempo

Métricas exatas de arquivos, bytes JavaScript, rotas e hash V2 estão em `phase2-metrics.json`. O esquema agora tem sete tabelas. Não foi realizado benchmark de CPU, memória ou carregamento; não há promessa de ganho de velocidade.

Os instantes são persistidos em UTC. Intervalos são tratados como `[início, fim)` e cortados pela meia-noite em `America/Sao_Paulo`; o somatório diário deve coincidir exatamente com foco/pausa da sessão. Pausas são separadas, inclusive na madrugada. Duração manual sem horários pertence à data escolhida e não recebe timestamps inventados.

Fechar o navegador/servidor não pausa automaticamente. A contagem continua e pode ser revista ao voltar. Após oito horas desde o início/última confirmação, retomar ou finalizar exige revisão. Informar horário de parada só ajusta o trecho de foco atualmente aberto; a edição de sessões ou intervalos anteriores não faz parte dessa ação. Confirmar a revisão sempre pausa o timer.

## 8. Pendências e próxima fase

Critérios da Fase 2 atendidos, incluindo duração manual e interrupção real do processo. Não foram feitos reinício físico do Windows, teste de queda de energia nem homologação em outra máquina. Essas verificações continuam na entrega final planejada.

A Fase 3 deverá construir os indicadores, exatamente dois gráficos, filtros, histórico paginado, correções auditáveis de sessões concluídas e exportação CSV, reconciliados com o rateio de intervalos. Por enquanto há as cinco sessões recentes e o detalhe por dia; a aba Análises continua sinalizada como próxima etapa. Restauração pela interface e registro automático do último backup também permanecem pendentes.
