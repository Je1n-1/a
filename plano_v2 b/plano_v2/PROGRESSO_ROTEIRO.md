# Roteiro integrado do Plano

Fonte: documento recebido em 28/09/2026, attachment 123d4ddd-091a-46c0-913a-7341a9f28736.
Destino único: `plano_v2 b/plano_v2`; banco: `instance/plano.db`.

## Estado

- Etapas 0–2: base visual, Formações, importador e grade existentes; reaproveitar.
- Etapas 3–5: página curricular, conteúdos e equivalências já existentes e reaproveitados.
- Etapa 3 entregue: `/subjects`, pesquisa, filtros de formação/situação,
  um item por grupo compartilhado, situações por curso e seleção de contexto.
  Retorno da disciplina mantém filtros; URLs antigas resolvem o ID de estudo
  para o ID curricular antes de redirecionar. Conferências focadas concluídas.
- Etapa 4 entregue: cadastro de conteúdos reaproveitado; conclusão direta na lista,
  inclusão ao final, ordenação por botões/teclado com proteção contra lista desatualizada
  e preservação explícita das avaliações legadas. Detalhes abaixo.
- Etapa 5 entregue: comparação com históricos consultáveis, avaliações preservadas
  por referência após desvincular e proteção do estudo compartilhado ao arquivar curso.
- Próximas: 6 Hoje/foco manual; 7 histórico; 8 análises; 9 início/configurações;
  10 isolamento do legado; 11 verificações focadas e entrega.

Nenhuma confirmação de equivalência ou conclusão real deve ser feita para testar.
Não ligar motor de planejamento, campanhas, revisões automáticas ou sincronizações.
Reutilizar tabelas de foco, sessões, pausas e notas; ajustes aditivos de banco.
Testes de escrita apenas em banco temporário. Registrar os resultados desta execução
sem reapresentar testes antigos como evidência nova.

Orientação posterior do usuário: entregar uma etapa por resposta. Etapa 5 solicitada
e entregue separadamente; parar aqui antes da Etapa 6. A preparação antiga da migration
0016 de foco foi retirada sem aplicação. A migration 0016 aplicada nesta etapa é
`0016_retained_assessment_access.sql`, exclusivamente para preservar avaliações.

Baseline desta execução: integridade ok, zero violações de chaves estrangeiras;
3 formações, 176 disciplinas, 47 estudos, 92 vínculos, 3 tópicos, 9 sessões,
17 blocos antigos, 3 revisões, 1 nota e 10 registros de foco. Os vínculos criados
pelo usuário desde a última entrega foram preservados.

## Conferências da Etapa 3 — 28/09/2026

- Um teste automatizado em banco temporário passou: agrupamento compartilhado,
  situações acadêmicas independentes, filtros no mesmo contexto, redirecionamento
  explícito de ID de estudo para ID curricular e integridade do banco de teste.
- Verificação de sintaxe de `static/js/disciplines.js` passou.
- Navegador: busca Circuitos mostrou duas matérias com quatro vínculos curriculares;
  selecionar Engenharia Elétrica abriu Circuitos Elétricos I desse curso (ID 237),
  e voltar à lista manteve a busca. Nenhum registro real foi editado no teste.
- Captura: `docs/etapa3-disciplinas.png`. Banco real permanece na versão 15.

## Arquivos desta etapa

- `database/repositories/manual_workspace.py` e `services/manual_catalog.py`:
  leitura do catálogo e agrupamento dos vínculos existentes.
- `routes/curriculum_workspace.py` e `routes/pages.py`: API e navegação por IDs corretos.
- `templates/disciplines.html`, `templates/workspace_base.html`,
  `static/js/disciplines.js`, `static/js/curriculum-subject.js` e
  `static/css/formations.css`: lista global, navegação e retorno com filtros.
- `tests/test_discipline_catalog.py`: conferência automatizada focada.

Limite: estudos pessoais antigos sem vínculo curricular são exibidos sem botão de
detalhes; a integração com estudo manual pertence à etapa Hoje/Foco. O banco real
verificado não possui registros dessa categoria. Nenhuma etapa posterior foi iniciada.

## Etapa 4 — Conteúdos e tópicos (28/09/2026)

Reaproveitados o modelo `topicos`, os campos opcionais da migration 15, APIs,
edição, remoção com prévia, arquivamento e restauração. Nenhuma migration nova.

Alterados:
- `services/curriculum_workspace.py`: novos tópicos entram no final da lista
  compartilhada; ordem inteira validada; versão da lista impede sobrescrever uma
  reordenação concorrente. Editar título/situação sem avaliar não converte domínio
  legado em uma nova autoavaliação explícita.
- `static/js/curriculum-subject.js`: botão Concluir por tópico; formulário sem
  ordem numérica obrigatória; setas acessíveis pelo teclado, foco mantido no item
  ao atingir a primeira/última posição; estado original visível também no arquivo.
- `tests/test_curriculum_workspace.py`: dois testes focados desta etapa.

Validação atual:
- Dois testes aprovados (0,388s): conteúdo opcional, inclusão/reordenação,
  repetição sem duplicar, conflito de ordem, estado legado, avaliações opcionais,
  independência entre conclusão acadêmica/tópicos/domínio, remoção sem vínculos,
  arquivo/restauração preservando sessões, anotações e avaliações. Integridade e
  chaves estrangeiras verificadas nos bancos temporários; sem agenda automática.
- Sintaxe do JavaScript aprovada.
- Navegador com banco temporário: criar apenas com título → subir por Enter →
  concluir tópico → recarregar. Ordem e conclusão persistiram; disciplina ficou
  Não iniciada, domínio Não informado. Nenhum erro/aviso de console nesse percurso.
- Captura da implementação com dados de teste: `docs/etapa4-conteudos-validacao.png`.
- Servidor real reiniciado em 5052: integridade ok, zero violações, versão 15/15,
  mesmas contagens da baseline (inclusive 3 tópicos e 9 sessões). Sem escrita de
  dados fictícios no banco pessoal.

Escopo: tópicos continuam opcionais. Estudo sem tópicos será conectado à execução
manual na Etapa 6; esta entrega não implementa cronômetro. Não foi feita bateria
visual/responsiva completa, conforme a preferência por verificações básicas.

## Etapa 5 — Equivalências e estudo compartilhado (28/09/2026)

Reaproveitados Comparar/Vincular/Manter separado, revisão dessa decisão, comparação
manual e por formação, confirmação explícita dos destinos da conclusão, transações,
repetição sem duplicar e referências de tópicos/sessões/notas ao desvincular.

Alterações:
- `migrations/0016_retained_assessment_access.sql`: tabela de referências para o
  histórico de autoavaliações, com chaves estrangeiras restritivas e chave composta
  que impede referências duplicadas; sem copiar avaliações ou reescrever a origem.
- `database/repositories/curriculum_workspace.py`: consulta das avaliações próprias,
  compartilhadas e preservadas, identificando formação de origem.
- `services/curriculum_workspace.py`: detalhe usa a consulta unificada de avaliações.
- `services/curriculum_equivalences.py`: prévia inclui sessões, textos das notas e
  avaliações; corrigir uma nota invalida uma comparação antiga mesmo sem mudar a
  quantidade de registros. Desvincular preserva referências às avaliações existentes;
  avaliações futuras continuam independentes depois da separação.
- `services/canonical_links.py`: arquivar uma formação preserva o estudo associado
  a outro curso não arquivado, inclusive matéria concluída ou ainda não iniciada.
- `static/js/equivalence-preview.js`, `static/js/curriculum-subject.js` e
  `static/js/formation-equivalences.js`: comparação compartilhada pelas duas entradas,
  com seções expansíveis para conferir os históricos antes de confirmar.
- `tests/test_curriculum_workspace.py`: dois cenários focados desta etapa.

Verificações executadas:
- Dois testes finais aprovados (0,443s): prévia desatualizada, escolhas de domínio,
  preservação de tópicos com títulos iguais, vínculo repetido sem duplicação,
  desvinculação/revinculação preservando referências e origem, manter separado/rever,
  destinos não autorizados, rollback de conclusão, conclusão repetida sem duplicação,
  arquivamento com estudo compartilhado concluído; sem foco/revisões/agenda criados.
- Sintaxe dos três módulos JavaScript aprovada.
- Navegação em banco temporário: comparar pela formação, abrir sessões/anotações,
  confirmar o vínculo (uma disciplina compartilhada, zero conclusões), tentar concluir
  pela grade, conferir destino desmarcado e cancelar; situação permaneceu Não iniciada.
  Sem erros/avisos de console nesse percurso.
- Captura real com dados de teste: `docs/etapa5-equivalencias-validacao.png`.
- Migration ensaiada em cópia temporária e aplicada ao banco real. Comparação por
  hash verificou todos os valores de 41 tabelas preexistentes sem alterações.
  Integridade ok, zero violações, versão 16/16. Servidor real reiniciado em 5052.
  Baseline desta etapa: 3 formações, 176 ocorrências, 47 estudos, 4 tópicos, 9 sessões,
  17 blocos antigos, 3 revisões, 1 nota, 10 focos antigos e 92 vínculos, preservados.

Limites mantidos: a comparação em lote aceita um par por grupo em cada confirmação;
para incluir uma terceira formação no mesmo grupo, confirmar o par e depois adicionar
a terceira. Não foi feita bateria visual/responsiva completa. Cronômetro é Etapa 6,
ainda não iniciada.
