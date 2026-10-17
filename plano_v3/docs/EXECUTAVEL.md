# Abrir o Plano sem terminal

Dê dois cliques em **Plano**, na área de trabalho. O atalho aponta para `Plano.exe` na pasta `plano_v3`. A página abre no navegador padrão depois de o servidor responder e confirmar o banco configurado.

Enquanto o servidor iniciado por ele estiver ativo, o ícone perto do relógio do Windows oferece:

- **Abrir Plano** (também disponível com dois cliques no ícone).
- **Abrir registro de inicialização** para consultar erros.
- **Encerrar servidor do Plano** para parar o processo iniciado pelo executável.

O Windows pode colocar o ícone na área de ícones ocultos. Fechar a aba não encerra o servidor. Encerrar o servidor não finaliza nem pausa uma sessão de estudo: use os controles do relógio antes de sair quando necessário.

Se o mesmo site já estiver rodando com o mesmo banco, o executável apenas abre a página. Se esse servidor foi iniciado manualmente, ele continua sendo encerrado pelo terminal que o iniciou. Outra aplicação na mesma porta é preservada e o iniciador exibe um erro.

## Arquivos e dados

Este executável é um iniciador local, não um instalador portátil. Ele depende de `app.py`, dos demais arquivos do site, de `.venv` e de `config.local.json`. Não mova apenas o executável. O banco permanece no caminho já configurado, fora da pasta do site. O iniciador não inicializa, migra ou substitui bancos ausentes.

O campo opcional `python_path` da configuração permite apontar para outra instalação Python compatível com as dependências já instaladas. Sem esse campo, é usada `.venv\Scripts\python.exe`.

Os registros ficam na pasta local de dados do Windows, em `PlanoV3\logs`. O caminho exato aparece em mensagens de erro e a opção do ícone abre o registro da execução. Eles contêm caminhos locais e mensagens do servidor.

## Recompilar

Com o iniciador encerrado, execute na pasta do site:

```powershell
.\desktop\build.ps1 -CreateShortcut
```

O script usa o compilador .NET Framework do Windows e gera um executável gráfico com ícone. Não instala pacotes nem altera `.venv`. Os fontes ficam em `desktop/Launcher.cs`; o executável e o ícone gerado são ignorados pelo Git. Sem `-CreateShortcut`, somente o executável é gerado.

Para encerrar por automação a instância iniciada por esse executável:

```powershell
.\Plano.exe --stop
```

Esse comando sinaliza somente o iniciador da mesma pasta. Não encerra um servidor aberto manualmente.

## Verificação isolada

```powershell
.\.venv\Scripts\python.exe desktop\verify.py
```

O teste cria uma instalação temporária com banco próprio, sem abrir o navegador. Verifica o formato gráfico do executável, abertura, reutilização sem duplicar o servidor, preservação de outro serviço na porta, encerramento da árvore de processos, persistência após reabrir e recusa de banco ausente. O caminho dos artefatos e o resultado são impressos ao final. O teste nunca aponta para o banco pessoal.

Referências de implementação: [CreateNoWindow](https://learn.microsoft.com/en-us/dotnet/api/system.diagnostics.processstartinfo.createnowindow?view=netframework-4.8.1) e [NotifyIcon](https://learn.microsoft.com/en-us/dotnet/api/system.windows.forms.notifyicon?view=netframework-4.8.1).
