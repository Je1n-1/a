# Relatório — organização, ritmo adaptativo, foco e calendário

Data da validação: 21/09/2026.

## Entrega funcional

O projeto existente foi evoluído de forma incremental. Formação, grade,
estudos, tópicos, revisões, sessões, notas, projetos e URLs anteriores foram
mantidos. As novas páginas canônicas são `/subjects`, `/subjects/new`,
`/subjects/:id`, `/subjects/:id/contents`, `/subjects/:id/settings` e as três
seções de `/settings`.

O cadastro de estudo livre aceita informações desconhecidas e cria um perfil
provisório. A recomendação distingue necessidade estimada, capacidade viável,
tempo alocado e déficit. O planejamento conjunto usa prévia versionada,
fingerprint dos dados de entrada e aplicação idempotente. Alteração concorrente
invalida a prévia; blocos manuais, bloqueados, realizados ou em foco continuam
protegidos.

O foco registra pausas como intervalos próprios. O relógio visual mantém escala
fixa de 60 minutos e mostra voltas/horas completas. Correções retroativas guardam
antes/depois, motivo e chave de idempotência. Histórico e análises exibem foco e
pausa separadamente, inclusive quando cruzam meia-noite.

## Banco e migrations

- `0012_adaptive_rhythm_focus_breaks.sql`: perfil provisório, baseline de
  esforço, observações, snapshots/decisões, versões de plano, finalidade de
  estudo/revisão, pausas e correções.
- `0013_google_calendar_outbox.sql`: conexão Google opcional, identidade externa
  por bloco e fila idempotente de sincronização/retry.

As migrations são aditivas. IDs e linhas preexistentes não são regravados.
Antes da primeira migration desta etapa foi criado o backup
`instance/plano.20260921-121000.before-0012-adaptive-focus.db`.

## Política adaptativa inicial

Versão `adaptive-v1`:

- referência por dificuldade 1–5: 120, 240, 360, 480 e 600 minutos por dia;
- domínio conhecido reduz essa referência pela parcela ainda não dominada;
- domínio desconhecido usa fator inicial 0,6 e permanece identificado como
  provisório;
- sem prazo, usa ciclo provisório de 28 dias;
- teto habitual padrão por disciplina: 240 min/dia;
- mudança de orçamento: passo de 15 min/dia somente após três observações
  consistentes;
- modo assistido: a sugestão não altera o ritmo aplicado sem confirmação;
- esforço explícito, sessão real, bloco planejado e disponibilidade nunca são
  somados como se fossem o mesmo fato.

Os valores ficam em `configuracoes` e podem evoluir sem mudar o significado do
histórico. Teto diário, teto semanal e teto por disciplina restringem novas
propostas, mas não alteram dificuldade nem removem blocos existentes.

## Exemplo reproduzível com três disciplinas

Exemplo de fixture isolada, sem inserir dados fictícios no banco do usuário:

| Disciplina | Perfil inicial | Sugestão antes | Observação | Sugestão depois |
|---|---:|---:|---|---:|
| Cálculo | dificuldade 5, domínio desconhecido | até 240 min/dia pelo teto padrão | 3 sessões ainda difíceis | +15 min/dia no orçamento, limitado pelo teto |
| Física | dificuldade 4, domínio 1/5 | distribuída até prazo/capacidade | 3 sessões com autonomia | −15 min/dia no orçamento |
| Inglês | ritmo manual 45 min/dia | 45 min/dia aplicado | avaliação opcional | sugestão histórica muda, ritmo manual não |

Com disponibilidade insuficiente, a prévia não força esses números: mostra o
déficit, o que cabe e o que ficou não alocado. Remover um bloco na prévia não
salva nada até **Aplicar plano**.

## Google Agenda e falhas

A fonte de verdade continua local. Somente planos aplicados entram na fila;
prévia nunca vira evento. Criar/repetir usa o mesmo vínculo externo, mover faz
update e cancelar exclui apenas o evento gerenciado pelo Plano. Uma falha deixa
estado `error`, agenda nova tentativa com backoff e não desfaz estudo, pausa ou
bloco local. Desconectar limpa a credencial protegida, sem presumir exclusão de
eventos externos.

Sem `PLANO_GOOGLE_CLIENT_ID` e `PLANO_GOOGLE_CLIENT_SECRET`, a interface informa
a dependência e mantém ICS/local funcionando. O teste com conta Google real não
foi executado porque credenciais externas não foram fornecidas; o adaptador foi
validado com transporte simulado.

## Validação executada

- compilação dos módulos Python;
- checagem sintática de `static/js/app.js` e `static/js/focus.js`;
- migrations 0012/0013 primeiro em cópia e depois no banco ativo, com
  `integrity_check=ok`, nenhuma violação de chave estrangeira e contagens
  preservadas: 3 formações, 176 itens de grade, 3 estudos, 3 tópicos, 9 sessões
  reais, 5 blocos planejados, 3 revisões e 9 sessões de foco;
- 117 testes automatizados aprovados, incluindo 9 casos novos para cadastro
  provisório/idempotente, tendência adaptativa, teto semanal/diário, prévia
  obsoleta, foco 25+5+20+10+15, correção retroativa, meia-noite, páginas diretas
  e Google Calendar simulado;
- navegação real no navegador sobre uma cópia do banco: Central de Disciplinas,
  cadastro guiado, detalhe/conteúdos, planejamento e prévia sem gravação,
  relógio de foco, pausa com motivo, histórico/detalhe, análises e integrações;
- teste responsivo em 390 px nas telas de foco e análises, sem rolagem
  horizontal; teste na largura normal confirmou o relógio e o caderno lado a
  lado;
- console do navegador sem avisos ou erros nas telas verificadas.

## Principais arquivos desta etapa

- backend: `services/core.py`, `services/adaptive_planning.py`,
  `services/focus_tracking.py`, `services/analytics_insights.py`,
  `services/google_calendar.py`, `services/smart_planning.py`;
- API/páginas: `routes/api.py`, `routes/calendar.py`, `routes/pages.py`;
- interface: `templates/page.html`, `static/js/app.js`, `static/js/focus.js`,
  `static/css/ui_refinement.css`;
- dados/testes: migrations 0012/0013,
  `tests/test_adaptive_focus_calendar_stage.py` e testes anteriores preservados.
