# Fase 5 — homologação e entrega local

Entrega em 10/10/2026. Instalação limpa, importação real, relógio, análises, backup e recuperação em cópia separada foram verificados. Reinício completo do Windows não foi executado; essa conferência permanece pendente e não é apresentada como aprovada.

## 1. Diagnóstico factual

Foram lidos o plano, `setup.ps1`, `run.ps1`, `backup.py`, `tracker/db.py`, rotas, parser, módulos de interface e testes existentes. Faltavam backup/recuperação pela interface e registro do último backup, requisitos do produto que ainda constavam como pendentes.

O comando `python` deste Windows apontava para o atalho da Microsoft Store, e `py` não estava disponível. A instalação limpa foi feita com o Python 3.12.14 existente no runtime local, informado explicitamente ao instalador. Não se afirma que foi instalado um Python global novo.

O usuário forneceu a pasta `C:/Users/jeanm/OneDrive/Desktop/dowloads`. Os três PDFs foram inspecionados por extração e renderização. Os de Engenharia Elétrica e Engenharia da Computação não produziram texto no leitor atual. O cronograma de Eletrotécnica apresentou um defeito reproduzível: a data de uma disciplina e o nome da seguinte vinham colados (`sex.Saúde...`), fazendo a segunda linha desaparecer da prévia. Antes da correção: 25 linhas, 1.208 h. Depois: 26 linhas, 1.220 h.

## 2. Plano mínimo

Completar as ações de armazenamento com validação e confirmação, sempre recuperando em arquivo novo. Reutilizar SQLite Backup API e diagnóstico, sem criar tabela ou migration. Corrigir apenas a fronteira de texto observada no cronograma e acrescentar regressão. Testar uma cópia limpa dos fontes com ambiente virtual e banco novos; conservar a instância pessoal durante o trabalho.

## 3. Mudanças efetivas

- `tracker/storage.py`: cópia SQLite com reserva exclusiva do destino, validação e remoção apenas da cópia recém-criada quando ela falha. Registro atômico da data/caminho do último backup em arquivo auxiliar `.last-backup.json`. Recuperação de upload V3 em diretório separado.
- `tracker/storage_http.py`: `POST /api/backups` e `POST /api/backups/recover`, ambos com confirmação explícita. Backup enviado como download; recuperação limitada a 64 MB, sem substituir ou ativar o arquivo recuperado.
- `tracker/http.py`, `app.py`, `backup.py`: diagnóstico mostra último backup; CLI e UI usam o mesmo serviço. Limite maior apenas para recuperação; importação de grade continua com 5 MB. Erros de armazenamento não registram conteúdo ou caminhos pessoais no log.
- `static/js/storage.js`, `shared.js`, template base e CSS: ações de backup no rodapé, acessíveis também no celular; módulo carregado apenas ao abrir. Confirmações, feedback de validação, resumo e caminho recuperado.
- `setup.ps1`: aceita `-PythonExecutable` e `-Port`, valida versão mínima antes de criar o ambiente e permite instalação isolada mesmo quando o alias de Python não funciona.
- `tracker/grade_parser.py`: separa a fronteira reconhecível entre abreviação de dia e nome colado, sem inventar disciplina ou carga. OCR não foi acrescentado.
- `tests/test_phase5.py`, `tests/browser_phase5.cjs`, README, `.gitignore` e `RECUPERACAO.md`: regressões, execução limpa e guia para verificar/promover manualmente uma cópia.

Sem novas dependências de execução, commit, push ou publicação externa. A pasta V3 continua como entrega local, ainda não adicionada em commit Git. A instalação de verificação usou uma cópia dos fontes, não um clone de uma versão publicada.

## 4. Segurança dos dados

Banco pessoal mantido em `PlanoV3/data/plano.db`, no caminho absoluto registrado em `config.local.json`. Esquema anterior e atual: `0001_tracker`, `0002_timer_recovery`, `0003_analytics`. As migrations foram comparadas com a cópia anterior e permanecem idênticas.

Durante as alterações, a cópia do código da Fase 4 serviu a porta 5054. Ao fim, a versão validada foi iniciada por `run.ps1` com o mesmo banco. Não foram importados cursos nem criados registros de homologação na base pessoal. Não se executou restauração sobre ela.

Os testes ficaram em `PlanoV3/verification/phase5-20261010-203115`, fora do OneDrive. A primeira base conserva o roteiro de relógio e a primeira tentativa de navegador; uma segunda base nova foi usada na repetição do roteiro final, sem apagar a primeira. Paths completos: `phase5-environment.json`.

Backups de homologação ficam em `backups` e as cópias recuperadas em `recovered`, sob esse diretório de verificação. O arquivo baixado pelo navegador também foi conferido. O SHA256 do banco V2 continua `64d27a914070a2abe783001162ca2f4bdbb8b8dc4319f930ab0c4bdd984602a6`.

## 5. Testes e comandos

No projeto:

```powershell
.\.venv\Scripts\python.exe scripts/check.py --fix
.\.venv\Scripts\python.exe scripts/check.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

48 testes aprovados. Os sete novos cenários cobrem cópia com relógio ativo e igualdade de linhas, exclusão de transação não confirmada do backup, exigência de confirmação/origem local, rejeição de banco inválido/legado/rateio inconsistente, recusa de sobrescrita e limite de upload, persistência do registro de backup e as duas linhas coladas do PDF.

Instalação limpa, com diretórios novos e sem reutilizar `.venv` ou banco pessoal:

```powershell
$qa = Get-Content docs/phase5-environment.json -Raw | ConvertFrom-Json
& (Join-Path $qa.clean_source 'setup.ps1') -DatabasePath $qa.browser_database -PythonExecutable 'C:\Users\jeanm\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -Port 5055
& (Join-Path $qa.clean_source 'run.ps1')
```

O setup inicial criou `test.db`; o campo `browser_database` passou a apontar para `test-run2.db` na repetição do roteiro. Os dois arquivos foram preservados. O ambiente novo instalou apenas `requirements.txt`; nele, os mesmos 48 testes passaram. Evidências: `phase5-clean-setup.log`, `phase5-clean-tests.log`, `phase5-installed-requirements.txt`.

Navegador Edge:

```powershell
$env:PLANO_TEST_ENVIRONMENT = 'docs/phase5-environment.json'
$env:PLANO_TEST_EVIDENCE = 'docs/phase5-clock'
node tests/browser_phase2.cjs
node tests/browser_phase5.cjs
```

O primeiro roteiro verificou novamente relógio, duas abas, perda de resposta, registro manual, recuperação longa e desconexão. O segundo verificou grade real, rejeições de PDF, estudo, backup, recuperação, erro de arquivo inválido, Escape e CSV.

Na primeira tentativa do segundo roteiro houve timeout: a automação selecionou um input da janela anterior antes da abertura assíncrona. A captura mostrou “Escolha um arquivo”. O roteiro foi corrigido para esperar a janela ficar visível e reexecutado numa base nova; passou. O erro não foi apagado das evidências (`phase5-failure.png`). Também houve uma tentativa auxiliar de importar `requests`, ausente no ambiente; as verificações HTTP usaram a biblioteca padrão e o Playwright, sem adicionar esse pacote.

## 6. Verificação visual e operacional

O cronograma foi importado pela interface, com prévia sem escrita, 26 disciplinas e reimportação sem duplicar. A soma das linhas inclui 20 h de ambientação além das 1.200 h declaradas; o aviso fica visível para revisão, sem correção automática dos números do documento. Os PDFs das engenharias retornaram mensagem específica de ausência de texto/OCR e não criaram disciplinas.

Uma disciplina importada iniciou o relógio diretamente; pausa, retomada e conclusão produziram histórico. Backup pela interface gerou download, exibiu data/caminho e recuperou uma cópia em arquivo novo. Um arquivo inválido foi rejeitado sem trocar o banco ativo. Duas visualizações continuaram presentes em Análises, e o CSV foi baixado.

Capturas de armazenamento e recuperação em 390 px foram abertas e inspecionadas: textos longos quebram linha, botões acessíveis e sem transbordamento da página. Também foram renderizadas páginas dos PDFs para comparar a estrutura com o texto extraído. Não houve erro JavaScript na execução final (`phase5-ui.json`).

Esquema e todas as linhas das nove tabelas coincidiram entre base de teste, backup e recuperação: um curso, 26 disciplinas, uma sessão, um timer, três intervalos, uma linha de rateio e três versões de migration. Reaplicar migrations não fez alterações. A integridade foi `ok`, com zero violações FK nos três arquivos (`phase5-recovery-comparison.json`).

O servidor de teste foi parado e reiniciado, preservando disciplinas, sessão e registro do backup (`phase5-restart.json`). Testes automatizados também interromperam processos abruptamente com relógio em estudo/pausado. As portas verificadas escutavam somente `127.0.0.1`, com debug desligado.

## 7. Comparação objetiva e limites das métricas

| Medida | V2 auditada | V3 entregue |
| --- | --- | --- |
| Regras Flask | 144 | 30 |
| Tabelas | 42 | 9 |
| Dependências diretas de execução | 5 | 5 |
| JavaScript | `app.js` sozinho: 428.590 bytes | Dez módulos: 55.814 bytes no total |
| Gráficos de análise | Conjunto anterior com planejamento | Dois gráficos sobre sessões reais |
| Histórico | Limite padrão de 100 registros | Paginação SQL; CSV inclui todos os registros filtrados |

Quarenta arquivos de produto da instalação limpa foram comparados byte a byte com a versão aplicada. O módulo de armazenamento é carregado sob demanda. As medições de latência da Fase 4 permanecem históricas; não foi realizado novo benchmark de desempenho da Fase 5 nem se atribui ganho geral de velocidade às mudanças desta etapa. O escopo funcional menor explica parte da diferença de tamanho em relação à V2.

## 8. Pendências e uso diário

Use `run.ps1` e abra `http://127.0.0.1:5054`. Para backup, use o botão no rodapé. Para conferir/restaurar uma cópia, siga `RECUPERACAO.md`; a troca do banco ativo é manual e preserva o arquivo anterior.

Pendências explícitas: reinício completo do Windows e conferência posterior; PDFs sem texto precisam de conversão/OCR fora do importador atual; CSV não foi aberto no aplicativo Excel. A recuperação não mescla históricos de bancos diferentes e não restaura dados pessoais que nunca estiveram na V3. Não há publicação externa nem integração Google/planejamento.

O servidor pessoal permanece ligado; instâncias de homologação são encerradas. Os fontes, testes, instruções e evidências estão nesta pasta, sem necessidade de reiniciar o Windows para usar a versão entregue agora.
