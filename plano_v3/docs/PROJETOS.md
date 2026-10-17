# Projetos — 16/10/2026

A aba Projetos reúne nome, objetivo, curso opcional, situação e etapas. Projetos
independentes não precisam de disciplina nem curso. Etapas e projeto têm
conclusões independentes: marcar todas as etapas não conclui automaticamente
o projeto. O progresso representa etapas concluídas, não horas trabalhadas.

## Uso

1. Abra Projetos e crie um projeto. Adicione suas etapas.
2. Use Trabalhar neste projeto ou Trabalhar nesta etapa. Hoje abre com a seleção
   preparada; o relógio só começa após Iniciar trabalho.
3. Pause, programe intervalos e finalize como no estudo de disciplinas. Anote o
   que foi feito. O registro aparece no projeto, nas sessões recentes e nas análises.
4. Registrar tempo permite informar duração/data ou início/fim manualmente.
5. Arquivar esconde o projeto da lista ativa e preserva etapas e histórico.

O projeto exibe as últimas 20 sessões. Ver análises abre o histórico paginado
filtrado por projeto; ali é possível corrigir duração, etapa, projeto ou nota,
informando motivo e mantendo a trilha de alterações.

## Análises

Mostrar oferece Tudo, Disciplinas e estudos avulsos, ou Projetos. No último modo,
os filtros específicos são projeto e etapa. O curso filtra também os projetos
vinculados. As métricas, os dois gráficos, a tabela e o CSV usam a mesma seleção.

Tudo soma estudo e trabalho uma única vez. Estudo avulso não inclui projetos
independentes. O gráfico de distribuição pode agrupar por atividade, disciplina,
projeto, etapa, curso ou tópico. Grupos específicos mostram apenas aquele tipo.
O gráfico diário e os indicadores usam tempo líquido. Pausa curta e intervalo
permanecem separados no histórico e CSV.

Cada sessão guarda nome do projeto, etapa e curso no momento do registro.
Renomear um projeto/etapa ou mudar seu curso não reescreve o histórico. Os
agrupamentos por projeto e etapa usam os identificadores, reunindo nomes antigos
e novos sem dividir a mesma atividade em várias barras.

## Dados e verificação

`0007_projects` cria projetos/etapas e acrescenta vínculos opcionais às sessões
e relógios existentes. A atualização usa backup, ensaio em cópia e comparação
integral das colunas e linhas anteriores. Não converte estudos em projetos.

Há um único relógio ativo para todas as atividades. Validação transacional impede
misturar disciplina e projeto, vincular uma etapa de outro projeto ou iniciar
em projeto arquivado. Edições verificam a versão para detectar conflitos entre abas.

- `tests/test_projects.py`: relógio, pausas e intervalos, retomada, notas, versões,
  vínculos inválidos, filtros/CSV, totais sem duplicação, correção, renomeação,
  migração e backup.
- `tests/browser_projects.cjs`: criação de projeto/etapas, conclusão, relógio,
  registro manual, análises, exportação, correção, arquivo/restauração e telas
  desktop/mobile em banco isolado.


Validação final: 83 testes automatizados passaram. O fluxo de navegador passou
sem erros JavaScript em desktop e mobile. A migração pessoal confirmou preservação
de todas as colunas e linhas anteriores; as 178 disciplinas continuam disponíveis.
O banco pessoal iniciou com zero projetos: os exemplos de teste ficaram somente
na base isolada. Backup e evidências estão na pasta local PlanoV3, em
`verification/projects-20261016/migration.json` e `personal-smoke.json`.
