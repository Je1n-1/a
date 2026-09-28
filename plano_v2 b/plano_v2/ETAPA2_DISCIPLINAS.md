# Plano V2 B — Etapa 2 entregue

## Correção do aproveitamento entre formações — 28/09/2026

A descoberta de equivalências deixou de depender de abrir cada disciplina.
Formações agora apresenta contagem de correspondências, possíveis aproveitamentos
de conclusão e disciplinas compartilhadas, com a ação **Comparar e aproveitar**.
A grade também identifica compartilhamentos confirmados e possíveis conclusões.

O fluxo permite buscar, filtrar conclusões disponíveis, selecionar correspondências
em conjunto, conferir os dois lados e resolver autoavaliações conflitantes. Os
destinos de conclusão começam desmarcados. Confirmar sem marcar destinos compartilha
conteúdos e mantém as situações acadêmicas. Cancelar a prévia não grava nada.
É possível manter separado, rever essa decisão e escolher manualmente disciplinas
com nomes diferentes. Importações passam a aparecer nesse mesmo fluxo.

O salvamento de todos os pares selecionados é transacional, verifica a versão
da comparação e protege contra repetição. Reutiliza as regras da Etapa 2 para
vínculos, referências de conteúdo e conclusão, sem chamar planejamento. Não houve
migration, reimportação nem confirmação de equivalências no banco pessoal.

Arquivos desta correção: `services/curriculum_equivalences.py`,
`routes/curriculum_workspace.py`, `static/js/formation-equivalences.js`,
`static/js/formations.js`, `static/css/formations.css` e
`tests/test_curriculum_workspace.py`.

Conforme orientação mais recente do usuário, foram executados **somente dois
testes automatizados focados**, ambos aprovados em banco temporário: vínculo com
conclusão opcional e repetição; salvamento de dois pares com rollback em conflito.
A sintaxe dos dois módulos JavaScript alterados também foi conferida. A bateria
antiga abaixo não foi reexecutada e não representa validação desta correção.
A validação de uso no navegador fica com o usuário; não houve nova captura visual.

Limite: selecione uma correspondência por disciplina/grupo em cada confirmação.
Para acrescentar um terceiro curso ao mesmo grupo, confirme o primeiro vínculo
e depois compare com o terceiro. O sistema avisa e não salva parcialmente quando
uma seleção contém grupos sobrepostos. Nomes iguais são sugestões, não garantia
de equivalência acadêmica.

---

## Registro da entrega anterior

Data da validação: 28/09/2026. Destino: `plano_v2 b/plano_v2`.
O projeto anterior foi usado como fonte de reaproveitamento, não como requisito
de compatibilidade visual ou de planejamento. Nenhuma cópia completa foi criada.

## Abrir e executar

Servidor do projeto novo nesta entrega: http://127.0.0.1:5052/formations.
Abra uma formação e clique no nome da disciplina. A rota `/curriculum/<id>` usa
explicitamente o ID curricular; não usa o ID de estudo da rota antiga `/subjects`.

O comando normal continua sendo `python app.py`, ou `./setup.ps1` e `./run.ps1`.
O padrão é porta 5051; `PLANO_PORT=5052` seleciona a porta usada nesta validação.
O banco ativo continua sendo `instance/plano.db`, salvo configuração explícita
de `PLANO_DATABASE_PATH`. O ambiente Python já instalado no projeto anterior
foi usado apenas como runtime nesta execução; nenhum serviço do site antigo é
necessário. `requirements.txt` continua sendo a lista de dependências.

## Percurso implementado

- Grade → disciplina → visão geral, conteúdos e vínculos, com abas na URL.
  Voltar conserva curso, busca e filtro da grade.
- Edição acadêmica: nome, código, formação, período, carga em horas, situação,
  datas opcionais e observações. Nenhum esforço pessoal obrigatório.
- Autoavaliações opcionais de dificuldade e domínio, escala 1–5 e Não informado.
  Mudanças ficam datadas. Valores antigos de domínio 0 continuam identificados
  como históricos; não são convertidos em 1 nem em ausência de informação.
- Conteúdos opcionais: criar, editar, ordenar por botões, concluir, remover,
  arquivar e restaurar. Tópicos com referências são arquivados; somente tópicos
  sem referências permitem exclusão. Estados legados pausado/para revisar são
  preservados. Conclusão acadêmica, conteúdo e domínio são independentes.
- Comparação de equivalências, decisão persistente de manter separado e revisão
  dessa decisão. Nome parecido nunca cria vínculo automaticamente.
- Vínculos compartilham conteúdos, referências a sessões/notas e autoavaliações.
  Não movem registros entre estudos nem copiam sessões, notas ou tópicos. IDs
  distintos com títulos iguais continuam distintos.
- Conclusão vinculada exige escolha antes da gravação, tanto na grade quanto no
  detalhe: somente atual, destinos selecionados ou cancelar. Destinos começam
  desmarcados. A API valida o grupo; repetição não duplica o histórico.
- Vincular a matéria de um curso recém-importado a uma concluída oferece o mesmo
  aproveitamento. Recusar mantém o vínculo de conteúdo e as situações separadas.
- Desvincular preserva as referências existentes e a origem. Conteúdos externos
  ficam em consulta; novos conteúdos deixam de circular entre os grupos. Vincular
  depois a um terceiro curso não reconecta o curso anterior indevidamente.
- Atualizações identificam disciplinas/formações afetadas e refletem em outra
  aba. Edições abertas são mantidas; alterações concorrentes são rejeitadas com
  mensagem para conferir os dados atuais. Erros não descartam o formulário.

Nenhum novo planejamento, agenda, cronômetro, gráfico, login, avatar ou controle
sem implementação foi adicionado.

## Código reaproveitado e fronteiras

`services/grade_import.py` foi mantido: extração e normalização continuam no
importador existente. `routes/formation_import.py` mantém prévia sem escrita e
confirmação transacional. As regras acadêmicas, histórico e validação de conteúdo
reaproveitam `services/core.py`. O cálculo de candidatas reaproveita
`services/canonical_links.py`, mas seu procedimento antigo de fusão não é chamado:
ele deslocava históricos, incompatível com esta etapa.

A criação de conteúdo recebeu uma opção explícita para não validar esforço do
planejador no percurso novo. A mudança acadêmica autorizada usa as datas acadêmicas,
sem depender de um prazo antigo do planejador. Demais contratos antigos permanecem.

Arquivos principais:

| Responsabilidade | Arquivos |
| --- | --- |
| Leitura e referências | `database/repositories/curriculum_workspace.py` |
| Gestão acadêmica, avaliação e tópicos | `services/curriculum_workspace.py` |
| Comparação, vínculo e desvinculação | `services/curriculum_equivalences.py` |
| API transacional | `routes/curriculum_workspace.py`, registro em `app.py` |
| Navegação HTML | `routes/pages.py`, `templates/curriculum_subject.html` |
| Estrutura compartilhada | `templates/workspace_base.html`, `templates/formations.html` |
| Interface | `static/js/workspace-ui.js`, `static/js/curriculum-subject.js`, `static/js/formations.js`, `static/css/formations.css` |
| Persistência adicional | `migrations/0015_curriculum_workspace.sql` |
| Testes e ensaio de migration | `tests/test_curriculum_workspace.py`, `scripts/verify_workspace_migration.py` |

## Migration e preservação do banco

A migration 0015 é aditiva: perfis opcionais, histórico datado de autoavaliações,
referência do perfil compartilhado, decisões de separação, acesso retido após
desvincular e chaves de repetição das operações. Mantém as tabelas e IDs existentes.
Um eventual registro interno de referência recebe `management_only=1`, sem
ativar planejamento. Se a referência antiga ainda atende outro grupo, uma
referência neutra independente evita reconectá-lo sem consentimento.

A atualização foi ensaiada em cópia SQLite temporária antes da aplicação real.
Foram comparados hashes de **todos os valores preexistentes de 35 tabelas**, não
apenas contagens. O resultado permaneceu idêntico depois da migration e ao final
da validação. Evidência: `VALIDACAO_ETAPA2_BANCO.json`.

- Migration ativa: 15/15, sem divergência de checksums.
- Integridade SQLite: `ok`; violações de chaves estrangeiras: zero.
- Banco real: 3 formações, 176 disciplinas, 4 estudos, 3 tópicos, 9 sessões,
  17 blocos planejados antigos, 3 revisões, 1 nota e 10 registros de foco.
- Esses dados foram usados somente para leitura no navegador. Nenhuma situação
  acadêmica, avaliação, sessão ou nota pessoal foi alterada para testar.
- No banco dos fluxos de teste, sessões planejadas permaneceram em zero.

## Resultados reais dos testes

Suite completa: `python -m unittest discover -s tests -q`:
**150 executados, 149 aprovados, 1 ignorado**, em aproximadamente 23 segundos.

Suite focada em Etapas 1/2, importação e gestão curricular:
**46 executados, 45 aprovados, 1 ignorado**. Há 19 testes novos de Etapa 2.
Cobrem campos opcionais, validação, URL curricular, independência das medidas,
criação/edição/ordenação/remoção de tópicos, legado 0, comparação obsoleta, conflitos
de avaliação, repetição, conclusão seletiva, destinos inválidos, rollback após
falha intermediária, curso importado depois da conclusão, histórico após
desvincular/revincular e ausência de novos planos. Todos os testes novos verificam
integridade, FKs e ausência de planos/baselines ao terminar.

Dois testes legados inicialmente falharam por usar a data real no serviço
adaptativo, embora fixassem o relógio de outro serviço. A mesma falha foi
reproduzida sem a migration 15 e sem a nova proteção de conclusão. Foram corrigidos
somente os relógios dessas fixtures para 21/09/2026, America/Sao_Paulo; o algoritmo
não foi alterado. Arquivos: `test_adaptive_focus_calendar_stage.py` e
`test_master_spec_completion.py`.

Os dois PDFs reais UNINTER encontrados em `Desktop/livros ADS` passaram pela
regressão do importador. O teste passou a procurar também nessa pasta. No navegador,
o PDF de Computação foi analisado, um código corrigido na conferência, a grade
salva no banco temporário e reaberta. Nenhum PDF foi reimportado no banco pessoal.

No navegador também foram verificados:

- Edição rápida e persistência após recarregar; nome curricular clicável e URL direta.
- Busca mantendo foco; retorno à grade mantendo o texto pesquisado.
- Criação, edição, ordenação, arquivamento/restauração e exclusão de tópico descartável.
- Comparar, manter separado, rever decisão, vincular e desvincular; sessão e nota
  continuaram acessíveis após desfazer o vínculo.
- Cancelar conclusão pela grade sem persistir; concluir somente um curso; selecionar
  outro e observar sua grade atualizar de 0% para 50% na segunda aba.
- Oferta de aproveitamento após vínculo com matéria concluída; cancelar manteve
  a matéria do outro curso como Não iniciada.
- Modal permaneceu aberto ao arrastar para fora e clicar no fundo. Descarte de
  rascunho usa confirmação interna; Continuar editando preservou o texto digitado.
- Navegação e edição por teclado; larguras 390, 768 e 1440px. Foram usados quadros
  de teste com largura efetivamente medida porque o override do navegador não
  mudou a janela. Não foi uma emulação completa de aparelho móvel.
- Sem erros JavaScript não tratados nos consoles das páginas do fluxo concluído.

Capturas em `docs/etapa2/`: `disciplina-dados-reais.png`, `vinculos-entre-cursos.png`,
`conteudos-390.png`, `formacoes-390.png`, `visao-geral-768.png` e
`visao-geral-1440.png`. Só a primeira usa o banco pessoal; as demais identificam
dados de teste. A leitura dos tópicos em 390px foi corrigida e recapturada após
identificar compressão excessiva causada pelos botões.

## Limitações e limite da etapa

- O PDF SENAI não foi encontrado: seu teste real ficou ignorado. A regra existente
  de alerta sobre 1.220h extraídas versus 1.200h declaradas não foi alterada, mas
  não se afirma uma nova validação desse arquivo ausente.
- Períodos ausentes são explicitados na conferência; nada é adivinhado. Avisos do
  importador continuam visíveis. Não foi implementado OCR para PDFs escaneados.
- Conteúdos preservados de um vínculo desfeito são referências, não cópias
  independentes: a edição continua na origem, explicada na interface.
- A comparação pessoal inicial mantém o valor legado 0. Depois que o usuário
  escolhe uma nova avaliação, a interface usa 1–5 ou Não informado.
- Cronômetro, planejamento, análises e outras etapas futuras não estão integrados
  à interface nova. O servidor local de desenvolvimento não é hospedagem pública.

Etapa encerrada para revisão, sem avanço para funcionalidades posteriores.
