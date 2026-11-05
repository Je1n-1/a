# Objetivos — entrega de 05/11/2026

O objetivo possui um caminho próprio, organizado em etapas e afazeres. Pode ser independente de cursos ou aproveitar disciplinas, conteúdos, projetos e etapas de projeto já cadastrados. A navegação fica no topo: Hoje, Objetivos, Disciplinas, Projetos e Análises.

## Uso

1. Em **Objetivos**, escolha **Novo objetivo com IA** e descreva o resultado que deseja alcançar, incluindo restrições e experiência quando forem relevantes.
2. Prepare e copie o texto. Ele inclui o catálogo atual para que uma IA externa possa sugerir vínculos pelos identificadores corretos. O site não envia dados a serviços de IA; o usuário decide onde colar o texto.
3. Converse com a IA e importe o JSON recebido, ou cole seu conteúdo no campo disponível.
4. Confira e ajuste descrições, estimativas em minutos, vínculos e pré-requisitos na proposta. Só **Adicionar objetivo** grava os dados.
5. Use **Ver objetivo completo** para percorrer todas as etapas. A página tem rolagem normal, filtros e **Expandir todas**.

A prévia é uma lista compacta: abra a etapa e clique no afazer para editar apenas aquele item. Os campos de experiência e tempo disponível são opcionais. A proposta em andamento fica em um rascunho no navegador e pode ser retomada após recarregar ou sair da página. Isso não substitui o backup do banco; limpar os dados do navegador apaga propostas ainda não salvas. O menu de estado de cada afazer reúne situação e revisão. Os vínculos abrem a disciplina, o conteúdo ou a etapa de projeto correspondente.

**Revisar caminho** permite editar a estrutura. Manter a chave do afazer e seu vínculo conserva o estado manual e a marca de revisão; remover um afazer da proposta remove esse afazer do objetivo ao salvar. As disciplinas, projetos e sessões originais permanecem intactos. Arquivar conserva o caminho e permite restaurá-lo.

## Progresso, revisão e tempo

- O percentual é a proporção de afazeres concluídos, sem ponderação pelas horas estimadas. Não representa uma avaliação de domínio.
- Afazeres independentes têm estado manual. Afazeres vinculados acompanham a origem; disciplinas dispensadas também contam como concluídas. Conteúdos e etapas com sessões, ainda não concluídos, aparecem em andamento.
- **Revisar depois** é separado da conclusão. Para conteúdos, altera a mesma marca de revisão usada em Disciplinas, com controle de versão. Para outros tipos e afazeres independentes, a marca pertence ao afazer do objetivo.
- Pré-requisitos incompletos ou com revisão pendente são indicados e podem ser clicados para localizar o afazer correspondente. A sugestão de próximo afazer só escolhe itens com requisitos atendidos, priorizando revisões e atividades em andamento. Isso não impede o usuário de registrar outro avanço manualmente.
- Horas previstas são estimativas. Horas registradas somam o histórico dos vínculos atuais, inclusive sessões anteriores à criação do objetivo. Mudar um vínculo muda o histórico consultado.
- Uma sessão que corresponda tanto à disciplina quanto ao conteúdo é contada uma única vez no total do objetivo e de cada etapa. Totais de afazeres, etapas ou objetivos com vínculos sobrepostos não devem ser somados entre si.
- Objetivos não escrevem sessões adicionais nas Análises. O cronômetro continua em Hoje. Neste incremento, afazeres independentes não recebem tempo automaticamente e exibem um traço nas horas registradas.
- As conclusões vinculadas são consultadas ao abrir o objetivo e ao retornar à aba. Não há sincronização periódica enquanto a página permanece aberta.

## Contrato JSON

```json
{
  "schema_version": 1,
  "objective": {
    "title": "Desenvolver uma automação funcional",
    "description": "Construir, testar e documentar uma solução concreta.",
    "stages": [{
      "key": "preparacao",
      "title": "Definir o resultado",
      "description": "Escolher o problema e os critérios de sucesso.",
      "tasks": [{
        "key": "definir_problema",
        "title": "Descrever o problema e os testes esperados",
        "description": "Registrar o comportamento que a solução deverá apresentar.",
        "planned_minutes": 60,
        "source": null,
        "requires": []
      }]
    }]
  }
}
```

`source` pode ser `null` ou um objeto com `kind` (`subject`, `topic`, `project`, `step`) e `id` existente no contexto. `requires` contém chaves de outros afazeres do mesmo objetivo. Não são aceitos ciclos, referências inexistentes ou o mesmo vínculo em mais de um afazer do objetivo. Limites: 30 etapas, 200 afazeres, chaves de até 60 caracteres, estimativas inteiras de 1 a 600000 minutos. A seleção de arquivo aceita até 1 MB. A IA não define conclusões nem horas registradas.

## Armazenamento e recuperação

A migration `0009_objectives` adiciona quatro tabelas próprias: `objectives`, `objective_stages`, `objective_tasks` e `objective_dependencies`. As migrations anteriores permanecem inalteradas. Gravações são transacionais, criações têm chave de repetição e edições verificam a versão do objetivo.

O banco ativo desta instalação é `C:\Users\jeanm\PlanoDados\data\plano.db`. As cópias desta atualização ficam em `C:\Users\jeanm\PlanoBackups\objetivos-20261104-153415`. O nome da pasta mantém o identificador do início do trabalho, não a data desta documentação.

A revisão de experiência de 05/11/2026 preservou também o código e o banco anteriores em `C:\Users\jeanm\PlanoBackups\objetivos-ux-20261105`. Essa revisão não exige outra migration.

Para atualizar outra instalação V3, pare seu servidor e execute `upgrade.py --database CAMINHO_DO_BANCO --backup-dir PASTA_SEPARADA`. O comando faz backup, ensaia a migration numa cópia e compara todos os valores preexistentes antes de confirmar a atualização. O iniciador `Plano.exe` não aplica migrations sozinho.

**Backup e armazenamento** continua copiando todo o banco, incluindo objetivos. Recuperar um backup V3 anterior migra uma cópia separada e não substitui automaticamente o banco ativo. Bancos V1/V2 não são convertidos por esse mecanismo. Para voltar ao código anterior, use também a cópia do banco anterior, preservando separadamente os registros posteriores; código antigo não deve abrir diretamente o banco atualizado.

## Validação

- 120 testes Python aprovados, incluindo oito cenários de objetivos: estados vinculados, revisão, horas sem duplicação, conflitos, importação inválida, dependências cíclicas, revisão do caminho, recuperação em cópia, sugestões e endereços dos vínculos.
- Teste de navegador de Objetivos aprovado: fluxo de IA/JSON, edição por item, revisão, filtros, recuperação de rascunho, atualização pela origem, navegação por requisitos, arquivamento/restauração, voltar/avançar e larguras de 320, 375, 768 e 1440 pixels.
- Regressões de navegador aprovadas: relógio e tópicos; concorrência de catálogos/importação; segurança e recuperação.
- Testes usam bancos temporários. Exemplos e capturas não são inseridos no banco pessoal.
