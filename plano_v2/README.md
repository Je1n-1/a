# plano. V2

Reconstrução limpa do organizador acadêmico. A V2 usa Flask, SQLite, Jinja2 e JavaScript puro; possui um único banco ativo em `instance/plano.db` e não lê nem migra o banco legado `plano.db` que possa existir na raiz.

Na inicialização, o aplicativo registra o caminho absoluto do banco ativo, a
versão das migrations e o resultado de integridade/foreign keys. Para suporte
local, `GET /api/diagnostics` informa esse estado e os estudos legados que
precisam de complementação. O banco só pode ser trocado de forma explícita por
`PLANO_DATABASE_PATH`; caminhos relativos são sempre resolvidos a partir da
raiz do projeto.

## Executar no Windows

```powershell
.\setup.ps1
.\run.ps1
```

 Abra `http://127.0.0.1:5051`. Essa porta é exclusiva da V2, evitando conflito com a aplicação legada.

Alternativa manual:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m database.migrations migrate
python app.py
```

## Verificação

```powershell
python -m unittest discover -s tests -v
```

O fluxo implementado preserva a separação entre Formação, Grade curricular e Estudos atuais. Sessões são a fonte de verdade do tempo; planejamento, recomendação e análises são derivados delas.

## Fluxo de uso

1. Em **Formações**, abra a grade e escolha **Iniciar disciplina**. O formulário
   salva, em uma única operação, o estado em andamento, o estudo atual e o
   perfil de prazo/esforço. Esforço e prazo podem ser informados, estimados pela
   carga ou deixados como provisórios.
2. Em **Planejamento**, configure a disponibilidade semanal e, quando preciso,
   use uma exceção para uma data ou uma faixa de datas. Mais de uma janela no
   mesmo dia é permitida; uma faixa não substitui as outras por acidente.
3. Clique em **Gerar plano** para revisar a prévia antes de aplicá-la. O motor
   distribui o restante até o prazo, respeita pausas, capacidade líquida e
   blocos manuais. Arraste um bloco, use `Alt` + setas ou a ação **Mover** para
   ajustar a agenda; converter um bloco automático em manual o protege dos
   próximos replanejamentos.
4. Inicie o foco por um bloco ou por uma sessão avulsa. O cronômetro fica no
   banco: pausar, retomar, fechar e reabrir a aba continuam no mesmo estado.
   Ao encerrar, a sessão real atualiza tópico, histórico, hoje e análises.
5. Quando duas grades tiverem a mesma disciplina, use **Possíveis
   equivalências** na ação da disciplina. A tela mostra apenas indícios; o
   vínculo e uma eventual união de históricos exigem prévia e confirmação.
   Os estados, notas e prazos acadêmicos continuam independentes por formação.

## Diagnóstico e calendário

- `GET /api/diagnostics` informa o caminho do banco ativo, migrations,
  integridade e itens legados que merecem revisão.
- A tela Planejamento oferece **Exportar calendário**, que baixa um `.ics`
  local. Nenhuma conta externa é exigida e nenhuma agenda é criada sem ação
  explícita da pessoa usuária.
- O diagnóstico é somente leitura por padrão. A reconciliação de estudos
  antigos sempre apresenta uma prévia e nunca apaga blocos manuais.

## Organização, ritmo e foco

- **Minhas disciplinas** fica em `/subjects`. O cadastro guiado em
  `/subjects/new` aceita dificuldade e domínio desconhecidos; tópicos continuam
  opcionais. A estimativa inicial aparece como provisória e só muda o ritmo
  aplicado por confirmação, salvo quando o modo automático é escolhido.
- **Configurações** centraliza teto diário/semanal, máximo habitual por
  disciplina, duração de blocos, pausas, descanso e disponibilidade. Tetos são
  limites de capacidade, nunca metas ou dificuldade adicional.
- **Planejamento** salva uma prévia versionada. Se disponibilidade, sessões ou
  agenda mudarem antes da aplicação, o servidor rejeita a prévia antiga. Uma
  repetição da mesma aplicação não duplica blocos e blocos manuais/bloqueados
  são preservados.
- **Foco** usa relógio circular fixo de 60 minutos, mostra horas completas e
  persiste cada pausa. Em Histórico, **Esqueci de pausar** registra uma correção
  auditável sem reduzir o foco duas vezes.
- **Análises** separa foco real, pausas, planejamento e recomendações. Intervalos
  que atravessam meia-noite são divididos por data no fuso configurado.

## Google Agenda opcional

O Plano continua totalmente utilizável sem Google. Para habilitar a autorização
OAuth local, crie um cliente do tipo aplicação Web no Google Cloud e configure o
redirect exato `http://127.0.0.1:5051/api/calendar/google/callback`. Antes de
iniciar o servidor, defina:

```powershell
$env:PLANO_GOOGLE_CLIENT_ID = "seu-client-id"
$env:PLANO_GOOGLE_CLIENT_SECRET = "seu-client-secret"
# opcional, quando a porta/URL for diferente:
$env:PLANO_GOOGLE_REDIRECT_URI = "http://127.0.0.1:5051/api/calendar/google/callback"
```

A conexão pede o escopo limitado
`https://www.googleapis.com/auth/calendar.events`. Tokens persistidos são
protegidos pelo DPAPI do Windows para o usuário atual. A sincronização inicial é
somente **Plano → Google** e alcança apenas blocos automáticos de um plano já
aplicado. IDs externos, hash, estado e fila de tentativa impedem duplicação;
falha de rede mantém o evento pendente sem desfazer dados locais. Desconectar
remove a credencial local e não apaga eventos externos sem uma decisão separada.

Referências oficiais usadas: [escopos do Google Calendar](https://developers.google.com/workspace/calendar/api/auth),
[OAuth 2.0 para aplicação Web](https://developers.google.com/identity/protocols/oauth2/web-server) e
[operações de eventos](https://developers.google.com/workspace/calendar/api/v3/reference/events).

O fluxo real com uma conta Google depende dessas credenciais externas. A suíte
automatizada valida criação, atualização, exclusão, retry e idempotência com um
transporte simulado; ela não acessa uma conta pessoal.
