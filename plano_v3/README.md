# plano. — V3 local

Registro de estudos em Flask, Jinja, JavaScript e SQLite. As Fases 1 a 4 e a homologação local da Fase 5 estão concluídas: cursos, disciplinas, importação com prévia, cronômetro durável, registros manuais, análises com histórico e CSV, revisão de manutenção, desempenho medido e backup/recuperação em cópia separada. O reinício completo do Windows continua como conferência manual pendente.

## Abrir nesta máquina

O ambiente e o banco V3 já foram preparados. Dê dois cliques no atalho **Plano** da área de trabalho. O executável inicia o servidor em segundo plano e abre o navegador, sem terminal. Também é possível abrir `Plano.exe` nesta pasta.

O ícone do Plano perto do relógio do Windows permite abrir a página ou **Encerrar servidor do Plano**. Fechar o navegador não encerra o servidor nem pausa o cronômetro. Finalize ou pause o estudo antes de encerrar, conforme sua intenção.

Mantenha o executável junto da pasta do site e do ambiente `.venv`: este é um iniciador para a instalação atual, não um pacote independente para outro computador. Ele usa o banco indicado em `config.local.json`, sem criar ou atualizar bancos. Veja [o guia do executável](docs/EXECUTAVEL.md).

Alternativa pelo PowerShell:

```powershell
Set-Location 'C:\Users\jeanm\OneDrive\Desktop\repositório_site_estudos\a\plano_v3'
.\run.ps1
```

Nesse modo alternativo, abra **http://127.0.0.1:5054** e mantenha o terminal aberto. Para encerrar, pressione Ctrl+C. O servidor usa somente o endereço local, com debug desligado.

O arquivo ignorado `config.local.json` aponta para o banco escolhido; `run.ps1` exibe esse caminho ao iniciar. No ambiente atual, o Windows resolveu o diretório de dados para:

```text
C:\Users\jeanm\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\PlanoV3\data\plano.db
```

Esse banco está fora do OneDrive e conserva os seus cadastros. Os registros artificiais dos testes ficam em outra base. Não apague os dados locais do aplicativo Codex sem antes guardar uma cópia desse banco em outro diretório. A V2 e seu banco continuam separados.

## Primeiro uso

1. Abra **Disciplinas**, crie um curso e clique em **Importar grade**.
2. Escolha XLSX, CSV, TSV, TXT, DOCX, PDF textual ou cole uma tabela. Quando houver várias planilhas, escolha a aba.
3. Confira os nomes, códigos, períodos, cargas e classificações na prévia. Marque as linhas desejadas ou use a seleção em lote. A prévia ainda não grava dados.
4. Confirme e confira as quantidades inseridas, atualizadas ou ignoradas. Repetir a mesma grade não duplica disciplinas no curso.
5. Clique em **Estudar** para preparar a disciplina em Hoje. Selecione ou crie um tópico, escolha Estudo/Revisão e clique em **Iniciar estudo**. Pause, retome e finalize com uma anotação opcional. As cinco sessões mais recentes aparecem abaixo do relógio. Use **Ver divisão por dia** para conferir o estudo e as pausas em cada data.

Também é possível cadastrar disciplinas manualmente, editar e arquivar cursos/disciplinas, restaurar arquivados ou começar um estudo avulso. Arquivar conserva os registros associados.

O modelo XLSX fornecido traz três disciplinas desmarcadas: selecione as linhas antes de confirmar. PDFs em imagem agora usam OCR local do Windows em português (até 12 páginas e 5 MB, limite de 90 segundos). Formatos fora das estruturas reconhecidas podem exigir correção na prévia ou uso da tabela modelo. Revise sempre a prévia.

## Relógio e registro manual

O SQLite guarda a sessão atual. Atualizar a página ou reiniciar o servidor recupera o mesmo relógio. Fechar a aba ou o servidor **não pausa** a sessão: o intervalo continua até você pausar ou revisar. Use **Revisar período** caso tenha esquecido o relógio ligado.

Depois de oito horas desde o início ou a última confirmação, é necessário revisar o período antes de retomar ou finalizar. Você pode confirmar o tempo registrado ou, enquanto o relógio está em estudo, informar quando parou desde a última retomada. Nesse caso, o restante vira pausa; os intervalos anteriores ficam preservados. A revisão fica registrada no banco e deixa o relógio pausado. Não existe limite de 60 minutos: o anel é apenas visual.

**Registrar estudo** aceita disciplina ou estudo avulso, nota opcional e uma destas formas:

- Data e duração: a interface aceita minutos inteiros, de 1 a 1.440. O registro é identificado como “Duração informada manualmente”, sem inventar horário de início/fim. A API aceita segundos inteiros entre 1 e 86.400.
- Início e fim: horários interpretados em `America/Sao_Paulo`, com duração de até 24 horas e sem horário futuro. Informe um intervalo contínuo de estudo; pausas não são inferidas. Se houver pausas, registre trechos separados ou informe a duração líquida.

Intervalos que atravessam meia-noite são repartidos por dia em São Paulo. Estudo, pausa curta e intervalo programado são somados separadamente, preservando todos os segundos. Um registro de duração sem horários pertence integralmente à data informada. Esta divisão alimenta os indicadores, os dois gráficos, o histórico e o CSV.

Se duas abas tentarem alterar o relógio, a versão persistida evita transições conflitantes. Um conflito atualiza a tela e solicita nova conferência; feche e reabra um formulário que tenha ficado desatualizado. Repetir uma finalização não gera outra sessão. Falhas de conexão são mostradas: o contador local é uma estimativa até reconectar.

## Análises e histórico

Em **Análises**, escolha datas, curso, disciplina e tópico e clique em **Aplicar filtros**. Cursos e disciplinas arquivados também aparecem para consulta do histórico. Use **Últimos 30 dias** para limpar os filtros.

- Os gráficos mostram **minutos líquidos por dia** e a **distribuição por disciplina, curso ou tópico**, sem planejamento ou projeções. Dias sem estudo permanecem visíveis com zero. Disciplinas homônimas de cursos distintos continuam separadas.
- **Hoje**, **Esta semana** (segunda-feira até hoje) e **Este mês** (dia 1 até hoje) respeitam curso/disciplina, usando suas próprias datas. **Período filtrado**, gráficos, tabela e CSV usam o intervalo selecionado. Os cards não devem ser somados entre si.
- Na tabela, bruto = líquido + pausas curtas + intervalos programados. Se o filtro pegar parte de uma sessão que atravessou a meia-noite, as durações representam somente essa parte. Os horários de início/fim continuam identificando a sessão completa.
- A tabela pagina 20, 50 ou 100 registros. **Exportar CSV** inclui todos os registros dos filtros aplicados, independentemente da página. O arquivo usa UTF-8 com BOM, ponto e vírgula, segundos inteiros e neutralização de campos que poderiam ser interpretados como fórmulas pelo Excel.
- Os contadores exibem horas:minutos:segundos. Os gráficos exibem minutos com até duas casas decimais; os totais continuam calculados em segundos. O período de uma consulta pode ter até 3.661 dias.

**Corrigir** exige um motivo e permite alterar disciplina/nota mantendo os intervalos, ou substituir o tempo da sessão inteira por uma duração/data ou por início/fim contínuos. As opções de substituição removem pausas e intervalos do resultado corrigido e avisam isso no formulário; o original permanece na trilha de alterações. A origem (cronômetro/manual) é preservada e a sessão recebe uma nova versão. **Alterações** mostra motivo, data e valores anteriores/novos. Repetir o envio não gera outra correção, e uma aba desatualizada recebe conflito.

As sessões e os intervalos são a origem dos dados. `session_days` guarda o rateio calculado na mesma transação de finalização, registro manual ou correção. A inicialização também confere se a soma diária coincide com os totais das sessões. Não edite essas tabelas manualmente.

## Instalação em outro ambiente Windows

Python 3.12 foi validado. Dentro desta pasta, escolha explicitamente um caminho local para os dados:

```powershell
.\setup.ps1 -DatabasePath 'C:\DadosLocais\PlanoV3\plano.db'
.\run.ps1
```

Se `python` abrir a Microsoft Store ou não houver `py`, informe um executável Python instalado: `./setup.ps1 -PythonExecutable 'C:\CAMINHO\Python312\python.exe' -DatabasePath 'C:\DadosLocais\PlanoV3\plano.db'`. O parâmetro opcional `-Port` permite testar uma segunda instalação sem ocupar a porta 5054. Nesta máquina, o ambiente já existe; basta executar `run.ps1`.

Escolha um diretório gravável e fora de pastas sincronizadas. O setup cria o ambiente virtual, instala `requirements.txt`, inicializa o esquema V3 e salva a configuração. Não aponte para o banco V2: ele é incompatível e será recusado. Iniciar o servidor não cria um banco ausente nem aplica migrations silenciosamente.

Os comandos equivalentes, sem scripts PowerShell, são:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py --database 'C:\DadosLocais\PlanoV3\plano.db' --init-db
.\.venv\Scripts\python.exe app.py --database 'C:\DadosLocais\PlanoV3\plano.db' --port 5054
```

Não edite migrations já aplicadas. Para evolução futura, crie uma nova versão e valide primeiro em cópia.

## Atualizar uma instalação existente

Nesta máquina, a atualização da Fase 3 já foi aplicada. O curso usado como teste foi excluído a pedido do usuário, após backup e confirmação de ausência de vínculos. Não é preciso executar a atualização novamente.

Para outra instalação V3, pare o servidor e use uma pasta de backup diferente da pasta de dados:

```powershell
$planoConfig = Get-Content config.local.json -Raw | ConvertFrom-Json
$planoBackupDir = Join-Path $env:USERPROFILE 'PlanoBackups'
.\.venv\Scripts\python.exe upgrade.py --database $planoConfig.database_path --backup-dir $planoBackupDir
.\run.ps1
```

O comando cria backup consistente, testa a migration em outra cópia e compara todos os valores das colunas já existentes antes de aplicar ao banco escolhido. Ele não apaga/substitui o arquivo original. Mantenha o servidor parado durante toda a atualização. Se houver erro, guarde os arquivos e a mensagem; não tente restaurar por cima do banco ativo.

## Backup explícito

A cópia usa a API de backup do SQLite e pode ser feita com o aplicativo aberto. Escolha um destino novo, fora da pasta do banco ativo:

```powershell
$planoConfig = Get-Content config.local.json -Raw | ConvertFrom-Json
$planoBackup = Join-Path $env:USERPROFILE ('PlanoBackups\plano-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.db')
.\.venv\Scripts\python.exe backup.py --database $planoConfig.database_path --output $planoBackup
```

O comando verifica o esquema, a integridade e as chaves estrangeiras; recusa sobrescrever um arquivo existente. A interface também permite criar/baixar backups e recuperar uma cópia validada em arquivo separado. O diagnóstico mostra a data e o caminho do último backup criado por esta versão; a data fica em um arquivo auxiliar `.last-backup.json`, fora das tabelas de estudo. Veja o [guia de recuperação](docs/RECUPERACAO.md).

Para verificar uma cópia sem sobrescrever o banco principal, inicie outra instância apontando explicitamente para ela em outra porta. Essa instância pode alterar a cópia caso você use funções de escrita.

## Validação e limites desta fase

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q app.py backup.py upgrade.py tracker tests
Get-ChildItem static/js/*.js | ForEach-Object { node --check $_.FullName }
```

Resultado atual: 65 testes automatizados aprovados, incluindo concorrência, interrupção abrupta, rateio, correções auditáveis, contrato de Hoje e reconciliação dos gráficos/histórico/CSV com mais de 100 sessões. Fluxos validados no Edge em desktop e largura de 390 px. Veja [a homologação da Fase 5](docs/FASE_5_ENTREGA.md) e [a entrega da Fase 4](docs/FASE_4_ENTREGA.md), [a Fase 3](docs/FASE_3_ENTREGA.md), [a Fase 2](docs/FASE_2_ENTREGA.md) e [a Fase 1](docs/FASE_1_ENTREGA.md).

O script `tests/browser_phase1.cjs` registra a reprodução realizada nesta máquina: usa o Playwright do runtime local e Edge, acessa a porta 5055 e exige um banco de teste recém-inicializado, sem cursos. Nunca execute esse script contra seus dados pessoais. A dependência de automação é apenas de verificação, não do site.

A instalação limpa, reinício de servidor e recuperação em base separada foram homologados. O reinício completo do Windows não foi executado; a troca do banco ativo por uma cópia recuperada permanece uma ação manual, documentada no guia. A lista recente de Hoje mostra cinco sessões; o histórico completo está em Análises. Não há planejamento ativo na V3.

O roteiro `tests/browser_phase2.cjs` usa a porta 5055 e uma base de verificação vazia, apontada em `docs/phase2-environment.json`. Ele simula perda de resposta, duas abas, registro manual e recuperação. As datas e o caminho do Playwright documentam o ambiente usado nesta entrega; ajuste-os para reproduzir em outra máquina. Não use esse roteiro contra seus dados pessoais.

O roteiro `tests/browser_phase3.cjs` usa dados sintéticos separados (124 sessões), verifica dois gráficos, paginação, exportação, correção, auditoria e estado vazio. As evidências em `docs/phase3-*` não representam o histórico pessoal. A verificação do CSV foi estrutural e por download no navegador; não houve abertura no aplicativo Excel instalado.

## Manutenção e medições

As rotas HTTP ficam em `tracker/http.py`, com regras nos serviços `tracker/` e transações em `tracker/db.py`. A interface usa módulos por página. Hoje carrega seu conjunto de dados em uma leitura consistente (`GET /api/today`); os formulários de registro manual, importação e correção são carregados ao abrir. Os endpoints anteriores continuam disponíveis.

Ferramentas opcionais de desenvolvimento (Python 3.12 e Node no PATH):

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe scripts/check.py
# Para aplicar a formatação e correções seguras do linter:
.\.venv\Scripts\python.exe scripts/check.py --fix
```

Ruff verifica/formata Python; jsbeautifier formata JavaScript; Node verifica sua sintaxe. As migrations ficam excluídas da formatação porque seus checksums já foram aplicados. Essas ferramentas não são necessárias para executar o site.

O benchmark cria bases sintéticas de 0, 1.000 e 10.000 sessões em um diretório de verificação explícito, inicia servidores temporários e os encerra. Reutiliza essas mesmas bases para comparação. Não use a pasta dos seus dados pessoais. Exemplo com Playwright instalado e Edge disponível:

```powershell
$planoBench = Join-Path $env:LOCALAPPDATA 'PlanoV3\verification\phase4-benchmark'
.\.venv\Scripts\python.exe scripts/benchmark.py --phase after --directory $planoBench
```

Os resultados completos estão em `docs/phase4-benchmark-before.json` e `docs/phase4-benchmark-after.json`; executar novamente substitui o relatório da fase escolhida. O script de navegador usa o caminho local de Playwright ou a variável `PLAYWRIGHT_MODULE`. A latência depende desta máquina e não é uma garantia para outros ambientes.

Para reproduzir a regressão de navegador da Fase 4, prepare uma **nova** base V3 separada, registre seu caminho como `browser_database` em `docs/phase4-environment.json` e sirva-a na porta 5055. Execute primeiro o roteiro de relógio e depois o de carregamento/importação/correção:

```powershell
$env:PLANO_TEST_ENVIRONMENT = 'docs/phase4-environment.json'
$env:PLANO_TEST_EVIDENCE = 'docs/phase4-clock'
node tests/browser_phase2.cjs
node tests/browser_phase4.cjs
```

Esses roteiros gravam dados sintéticos e não são idempotentes. A Fase 4 usa datas de outubro de 2026; adapte as amostras quando necessário. Nunca os execute na porta ou banco pessoais. O roteiro histórico da Fase 1 contém uma expectativa da antiga tela provisória de Análises; a regressão atual do importador está em `browser_phase4.cjs`.

## Homologação com seus arquivos

O cronograma real de Eletrotécnica foi testado em base separada: 26 linhas reconhecidas e reimportação sem duplicar. A leitura de uma linha colada à anterior foi corrigida. A soma das linhas inclui a ambientação e difere do total declarado; a prévia mostra o aviso e permite desmarcar/editar antes de confirmar.

Os PDFs de Engenharia Elétrica e Engenharia da Computação agora são importados com OCR local: 19 disciplinas únicas em cada arquivo. As quatro páginas de cada PDF repetem o mesmo trecho; 57 ocorrências repetidas são reunidas e a prévia avisa que pode não ser a grade completa. O cronograma continua com 26 disciplinas. Os três arquivos foram confirmados e reimportados pela interface sem duplicatas, em base separada. Nenhum curso de homologação foi inserido no seu banco pessoal. Veja [a correção e as evidências](docs/CORRECAO_IMPORTACAO_PDFS.md).

As evidências `docs/phase5-*` registram instalação isolada, testes, interface e igualdade do banco recuperado. O roteiro `tests/browser_phase5.cjs` usa os caminhos de verificação em `docs/phase5-environment.json`, requer uma base sem cursos e aceita `PLANO_REAL_GRADE_FOLDER` para localizar os três PDFs; não o execute na base pessoal.

O suporte OCR usa Windows PowerShell e o recurso nativo de reconhecimento de texto em português. Se o recurso estiver ausente em outra máquina, a importação informa isso; os demais formatos continuam disponíveis. Não há envio do PDF para serviços externos. O roteiro `tests/browser_pdf_ocr.cjs` usa os três arquivos reais e a base isolada indicada em `docs/ocr-environment.json`; exige uma base nova, sem cursos.


## Tópicos e revisão manual

A atualização de UX adiciona tópicos por disciplina. É possível criar um tópico no próprio início do estudo, reutilizá-lo em várias sessões e consultar seu tempo acumulado. Concluído e Precisa de revisão são escolhas independentes. Finalizar uma revisão não limpa a pendência automaticamente: escolha explicitamente Revisão realizada / sem pendência.

A lista de disciplinas permite alterar a situação diretamente e abrir os Tópicos. O botão Tópicos para revisão mostra pendências do curso. O histórico oferece Estudar novamente, que prepara uma nova sessão sem alterar a anterior. O estudo avulso e as sessões sem tópico continuam disponíveis.

A migration 0004_topics adiciona campos opcionais, mantendo sessões antigas sem vínculo inventado. Para outra instalação V3, use o procedimento de atualização explícita acima, com servidor parado. Backups V3 anteriores conhecidos podem ser recuperados: somente a cópia recebida é migrada e validada, sem substituir o banco ativo.

Os indicadores de tempo registrado incluem apenas sessões finalizadas, com pausas e intervalos descontados. O indicador global mostra a sessão ativa ou pausada em qualquer página, usando o mesmo relógio persistido.

Veja o [relatório de UX, testes e migração](docs/UX_TOPICOS_ENTREGA.md). A base pessoal estava vazia na atualização; os testes com histórico preenchido usaram bancos separados. A verificação desta etapa foi exclusivamente desktop.


### Pausa curta, intervalo e conteúdo colado

**Pausa curta** registra interrupções rápidas. **Intervalo de estudo** programa um
horário de retorno ou uma duração, com aviso sonoro. Durante o intervalo, o
contador de pausa curta fica parado. O descanso continua até Retomar, mesmo
após o alarme; Silenciar aviso apenas desliga o lembrete. Os três tempos ficam
separados no relógio, histórico e CSV.

Em **Disciplinas → Tópicos → Colar conteúdo para separar**, cole uma lista do AVA
ou sumário, escolha o tipo de separação e revise os títulos antes de confirmar.
O atalho também está em Hoje, depois de selecionar a disciplina. A prévia é
editável e não grava dados; títulos longos não são cortados automaticamente.
**Separar este texto** reaproveita um tópico existente, preservando o original
e seu histórico. Prints ainda precisam ter seu texto extraído antes de colar.


Em Hoje, a escolha de disciplinas está agrupada em **Em andamento**, **Para
revisar**, **Concluídas** e **Outras disciplinas**, nessa ordem. Revisão significa
ter ao menos um tópico marcado como Precisa de revisão. Uma disciplina em
andamento permanece no primeiro grupo mesmo com revisão pendente; uma concluída
com essa pendência entra em Para revisar. Cada disciplina aparece uma vez.
A sugestão segue os grupos e os filtros de curso/busca; dentro do grupo, usa ordem
alfabética. Selecioná-la prepara a sessão sem iniciar o relógio.


### Projetos

A aba **Projetos** permite cadastrar objetivo, curso opcional e etapas, acompanhar
conclusão e consultar os registros de trabalho. **Trabalhar neste projeto** abre
o relógio de Hoje; **Registrar tempo** permite lançar atividade manualmente.
Em Análises, **Mostrar → Projetos** oferece filtros de projeto e etapa; **Tudo**
soma estudo e trabalho sem duplicar horas. Consulte [Projetos](docs/PROJETOS.md)
para detalhes de uso, histórico, backup e validação.
