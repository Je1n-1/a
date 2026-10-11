# Backup e recuperação do Plano V3

## Criar uma cópia

Abra **Backup e armazenamento** no rodapé de qualquer página (também disponível na barra lateral no desktop), clique em **Criar backup** e confirme **Criar e baixar**. O site usa a API de backup do SQLite, verifica esquema, integridade, relações e rateio de tempo e guarda uma cópia local. O navegador também baixa o arquivo `.db`. A data da última cópia passa a aparecer no diagnóstico.

Pode haver um relógio em andamento durante o backup. O arquivo conserva esse estado, assim como cursos, disciplinas, sessões, pausas e correções. Guarde também o download em outro dispositivo: uma cópia no mesmo disco não protege contra perda desse disco.

Na configuração pessoal atual, as cópias locais ficam em `PlanoV3/backups`, ao lado da pasta `data`. O caminho completo aparece no diagnóstico. O comando `backup.py` do README usa o mesmo serviço e registra a data. Arquivos antigos criados antes dessa implementação não recebem uma data retroativa inventada.

## Recuperar sem substituir os dados ativos

1. Em **Backup e armazenamento**, escolha **Recuperar uma cópia**.
2. Selecione um backup V3 de até 64 MB, gerado por esse fluxo ou por `backup.py`.
3. Marque a confirmação de recuperação em arquivo separado e clique em **Validar e recuperar**.
4. Confira o caminho, os números de cursos/disciplinas/sessões e o tempo recuperado. O arquivo novo fica em `PlanoV3/recovered`, separado do banco ativo.

A recuperação não importa a V2, não aplica migrations nem troca o banco em uso. Backups incompatíveis, danificados ou com rateio inconsistente são recusados. Para um backup de versão anterior, conserve o original, faça outra cópia e use o procedimento de atualização documentado no README.

Não envie apenas uma cópia de arquivo feita com o SQLite aberto: transações podem estar em arquivos auxiliares. Use o backup consistente do aplicativo. Nenhum destino existente é sobrescrito.

## Conferir o arquivo recuperado

Copie o caminho exibido na tela e, em um segundo PowerShell, na pasta do projeto, use outra porta:

```powershell
.\.venv\Scripts\python.exe app.py --database 'C:\CAMINHO\EXIBIDO\plano-recuperado.db' --port 5056
```

Abra `http://127.0.0.1:5056`. Confira o caminho em **Backup e armazenamento**, os cursos e os totais de Análises. Essa instância usa a cópia; ações como finalizar ou corrigir estudos alteram somente ela. Um relógio que estava em andamento no backup continua em andamento quando essa cópia é aberta; confira **Revisar período** antes de finalizar.

Encerre a instância de conferência com Ctrl+C. Para arquivos maiores de 64 MB, a validação pode ser feita por essa abertura local, sem upload; o aplicativo recusa esquema ou integridade incompatíveis.

## Passar a usar a cópia validada

Essa é uma escolha manual. Antes de fazer a troca, crie um backup recente do banco atual, pare as duas instâncias e conserve o arquivo original.

Em `config.local.json`, altere somente `database_path` para o caminho absoluto do arquivo recuperado já conferido. Mantenha a porta desejada e execute `run.ps1`. Confirme novamente o caminho no diagnóstico. Não copie o recuperado por cima do banco antigo.

Para voltar ao original, pare o servidor, restaure seu caminho em `config.local.json` e inicie novamente. Isso troca qual arquivo é aberto; não combina históricos divergentes. O histórico criado em uma cópia depois da troca não é transferido automaticamente para outra.

## O que foi realmente testado

Na homologação, backup e recuperação passaram tanto pela API quanto pelo navegador. Foram comparados o esquema e todas as linhas das nove tabelas; integridade, FKs e tempos coincidiram. O banco ativo continuou no mesmo caminho. Houve teste de backup com relógio ativo e com uma transação ainda não confirmada, que corretamente não entrou na cópia.

O servidor foi parado e iniciado de novo; dados e registro do último backup persistiram. Reinício completo do Windows não foi executado nesta sessão. Após seu próximo reinício habitual, abra `run.ps1`, confira o caminho do banco e o estado do relógio. Fechar o programa ou desligar o computador não representa uma pausa automática no estudo.
