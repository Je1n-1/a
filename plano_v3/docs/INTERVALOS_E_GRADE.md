# Intervalos programados e grade em módulos

Atualização de 14/10/2026.

## Intervalos

Em Hoje, com um estudo aberto, use **Intervalo de estudo**. É possível informar
uma duração de 1 a 1.440 minutos ou um horário de retorno nas próximas 24 horas
(São Paulo). Ao confirmar, o estudo entra em **intervalo programado**. A ação
**Pausa curta** é separada: o contador dela fica parado durante o intervalo.
Programar um intervalo depois de uma pausa fecha a pausa naquele instante;
alterar o prazo de um intervalo já aberto preserva seu início.

O prazo fica no SQLite (`0005_scheduled_break`) e é recuperado ao recarregar ou
reabrir. A contagem aparece também nas outras abas do site. Ao zerar, há aviso
visual e som; o estudo continua em intervalo. **Silenciar aviso** cancela o lembrete,
sem retomar. **Retomar** encerra o intervalo; **Trocar para pausa curta** termina
o descanso programado e começa a pausa curta. Finalizar ou descartar também remove
o lembrete. Conflitos entre abas continuam protegidos pela versão do relógio.

Para tocar no horário, o navegador e o computador precisam permanecer ativos.
O site não instala um alarme no sistema operacional. Se o navegador bloquear
reprodução automática após recarregar, aparece **Ativar / testar som**. O alarme
consulta o estado salvo antes de tocar e uma trava do navegador evita som
simultâneo em várias abas quando a API de locks está disponível.

O banco (`0006_rest_time`), o relógio, o histórico, o rateio diário e o CSV
distinguem estudo, pausa curta e intervalo. Tempo bruto é a soma dos três;
tempo líquido inclui apenas estudo. O vencimento do aviso não troca o tipo de
descanso automaticamente. Registros encerrados anteriores mantêm seus valores,
sem estimar a intenção das pausas antigas. Um descanso ainda aberto com prazo
salvo é reconhecido na migração; suas colunas antigas permanecem intactas.

## Separar conteúdo em tópicos

Em **Disciplinas → Tópicos → Colar conteúdo para separar**, cole texto do AVA
e escolha linhas/marcadores, ponto e vírgula ou sumário com páginas. Confira a
prévia editável, desmarque itens indesejados e confirme. O mesmo fluxo está na
seleção de tópico de Hoje. **Separar este texto** reaproveita um tópico existente
sem apagar o original nem redistribuir seu tempo estudado.

Nomes repetidos são ignorados por disciplina. Títulos acima de 200 caracteres
precisam ser divididos ou editados: não são truncados. A confirmação inteira é
atômica. A prévia não grava dados e não inventa continuação de texto incompleto.
O modo de páginas é uma heurística explícita: números relevantes dentro dos
títulos exigem revisão. Não há upload/OCR de prints neste fluxo; texto reconhecido
por uma ferramenta externa pode ser colado e revisado aqui.

## Importação e catálogo

A prévia de importação e o catálogo agrupam as disciplinas pelo campo módulo /
período. O catálogo tem cartões de progresso por módulo, busca sem acentos e
atalhos para os blocos. Concluídas e dispensadas compõem o progresso acadêmico;
esse progresso não é uma medida de tempo estudado.

Os PDFs de engenharia fornecidos contêm o mesmo trecho visível em quatro páginas.
Quando o OCR encontra linhas repetidas, a prévia destaca a possibilidade de uma
grade incompleta e exige a conferência desse aviso antes da confirmação. O OCR
não preenche lacunas com disciplinas obtidas da internet.

Neste atendimento, o usuário autorizou complementar as transcrições com as grades
gerais oficiais da Uninter. Foram preparados 76 componentes de Computação,
76 de Elétrica e 26 de Eletrotécnica. Em cada engenharia, 19 componentes vêm do
PDF e 57 da página oficial. Nas observações fica registrada a origem. As quatro
vagas de eletivas de Computação permanecem como vagas, com as opções nas notas,
sem somar as 12 alternativas como disciplinas obrigatórias adicionais.

O cronograma técnico soma 1.220 horas incluindo Ambientação (20 h), embora o
total declarado seja 1.200 h. Essa diferença da fonte não foi corrigida inventando
ou removendo carga horária.

## Verificação

- Testes de prazo persistido, pausa real após o vencimento, alteração/cancelamento
  do aviso, entrada inválida e conflito de versão: `tests/test_scheduled_break.py`.
- Fluxo no navegador em banco isolado: `tests/browser_intervals.cjs`, com PDF real,
  agrupamento, aviso de repetição, complemento sem duplicatas, recarga, navegação,
  contagem a zero, geração do som, silêncio, retomada e conclusão.
- A migração usa o procedimento existente de backup, ensaio em cópia e comparação
  integral das colunas e registros anteriores antes de liberar o servidor.

Na entrega da grade, 69 testes automatizados passaram. O fluxo de navegador passou
sem erros JavaScript. No banco pessoal, os três cursos somam 178 componentes
(76, 26 e 76), com origem nas observações. Os registros anteriores de sessões,
intervalos, tópicos e correções foram comparados com o backup e preservados.
Computação e Eletrotécnica já estavam preenchidas no momento da aplicação; seus
registros foram reaproveitados e anotados, e Elétrica recebeu os 76 componentes.


Na atualização da pausa curta e separação de conteúdo, 76 testes passaram.
`tests/browser_rest_topics.cjs` confirmou em banco isolado: pausa congelada
durante intervalo, alarme, silêncio, troca de tipo de descanso, conclusão,
histórico com três tempos, prévia editável, duplicatas e títulos longos.
A interface foi conferida em desktop e tela pequena, sem erros JavaScript.
A migração pessoal preservou todas as colunas e registros anteriores e
reconheceu o intervalo programado ainda aberto. Evidências e backup estão na
pasta local PlanoV3, em `verification/rest-topics-20261014/migration.json`.
