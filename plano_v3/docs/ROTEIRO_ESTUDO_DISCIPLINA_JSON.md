# Roteiro de estudo por disciplina — contrato JSON

O Plano prepara um prompt com o contexto da disciplina para o usuário copiar a uma IA externa. O usuário anexa o PDF diretamente à IA e cola a resposta no Plano. O aplicativo não recebe o PDF, não chama serviços de IA e não guarda credenciais.

## Formato aceito

```json
{
  "schema_version": 1,
  "kind": "subject_study_route",
  "route": {
    "title": "Roteiro principal",
    "description": "Organização dos conteúdos da disciplina.",
    "modules": [
      {
        "key": "fundamentos",
        "title": "Fundamentos",
        "description": "Conceitos iniciais.",
        "topics": [
          {
            "key": "lei_de_ohm",
            "title": "Lei de Ohm",
            "description": "Relacionar tensão, corrente e resistência.",
            "estimated_minutes": 60,
            "source_reference": "Plano de ensino, unidade 1",
            "existing_topic_id": null
          }
        ]
      }
    ]
  }
}
```

`schema_version` precisa ser `1` e `kind`, `subject_study_route`. O destino é sempre a disciplina em que a importação foi aberta. Há limite de 1 MB, 30 módulos e 300 tópicos no total. Chaves aceitam 1–60 caracteres ASCII alfanuméricos, hífen ou sublinhado e precisam ser únicas no roteiro. Títulos aceitam até 200 caracteres; descrições até 2.000; referências até 500. `estimated_minutes` é opcional, inteiro de 1 a 600.000. `existing_topic_id` é nulo ou um tópico da mesma disciplina.

O JSON não pode definir conclusão, revisão, status, horas realizadas nem sessões. A prévia não grava nada. Correspondências exatas são sugeridas; correspondências aproximadas exigem escolha explícita. Duplicações no próprio JSON precisam ser removidas ou corrigidas antes da confirmação.

## Persistência e histórico

A migration `0010_study_routes` guarda um roteiro principal por disciplina, seus módulos ordenados e itens que apontam para `topics.id`. `topics` continua sendo a fonte canônica de estados e histórico. Trocar um roteiro remove apenas seus módulos/itens antigos; tópicos, sessões e nomes históricos permanecem. A mesma importação não aumenta a versão nem recria itens. Cada confirmação valida a versão esperada e grava toda a alteração em uma transação.

Na aba Hoje, o roteiro fica pré-selecionado quando existe. Os tópicos são agrupados por módulo e tópicos fora do roteiro continuam disponíveis no grupo separado. O cronômetro e as sessões continuam usando o `topic_id` já existente.

## Atualizar uma instalação já usada

O app não executa migrations automaticamente. A atualização deve ser feita depois de fechar o Plano e criar um backup novo e verificado. A migration foi ensaiada em uma cópia isolada do backup; cursos, disciplinas, tópicos, relógios, sessões, rateios, projetos e objetivos mantiveram suas contagens, com `integrity_check=ok` e sem violações de chaves estrangeiras. Nenhum banco pessoal foi migrado durante esta implementação.

Depois de conferir o caminho do banco ativo e guardar o backup fora da pasta do app, execute explicitamente, na pasta `plano_v3`:

```powershell
python app.py --database "CAMINHO_ABSOLUTO_DO_BANCO_V3" --init-db
```

Confirme que a saída inclui `0010_study_routes`; em seguida, inicie o Plano normalmente. Não execute esse comando em uma cópia errada, no banco de outra versão, nem enquanto o app estiver aberto. Se a validação falhar, não inicie o app; preserve os arquivos e restaure o backup verificado.
