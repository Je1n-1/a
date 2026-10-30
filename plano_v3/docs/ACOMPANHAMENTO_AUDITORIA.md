# Acompanhamento da auditoria — 30/10/2026

Origem: AUDITORIA_TECNICA_PLANO_V3.md fornecida pelo usuário. Este registro distingue correções entregues de recomendações e validações ainda pendentes. A auditoria completa **não está concluída**.

## Preservação e linha de base

- Banco original conferido: integridade OK, sem violações de chaves estrangeiras; migrations históricas 0001–0007 preservadas.
- Backup consistente: `C:\Users\jeanm\PlanoBackups\auditoria-20261030-115045\antes-auditoria.db`.
- Restauração em arquivo separado comparada com o backup: `restauracao-conferida.db` na mesma pasta.
- Fontes anteriores guardados em `fonte-antes.zip`; configuração anterior em `config-anterior.json`. Alterações preexistentes do relógio foram preservadas.
- Linha de base: 83 testes Python aprovados. Após este lote: 91 aprovados. Runtime Python 3.13 instalado no computador; a antiga `.venv` não estava presente e não foi recriada/modificada.
- Testes atuais de navegador: Edge/Playwright, banco temporário, recuperação após 8 horas, início com tópico, pausa, retomada, intervalo, finalização, descarte e recarregamento. Grades de filtros e ausência de transbordamento da página conferidas em 320, 375, 390, 600, 700, 768, 1024, 1100 e 1440 px.
- Evidência do navegador: `C:\Users\jeanm\AppData\Local\Temp\plano-timer-controls-a8NxgX\result.json`.

## Entregue neste lote

| Achado | Tratamento |
|---|---|
| F01 | Contrato simplificado: datas e ordem da origem são incorporadas às observações na prévia, preservadas na confirmação/reimportação e acompanhadas de aviso. Não há agendamento nem ordenação automática. A tela já guardava datas nas notas; agora a API de prévia também preserva ordem e datas. Não foram criadas colunas de planejamento. |
| F02/F03 | Cargas extremas, infinitas, negativas, fracionárias em minutos e fora de 1–600.000 minutos são bloqueadas na prévia. Nomes, códigos, períodos e notas também passam pelas regras do cadastro. |
| F05 | A condição existente já detectava páginas sem texto, mas submetia o documento inteiro a OCR. PDFs mistos agora mantêm o texto nativo e enviam somente as páginas necessárias ao OCR, recombinando na ordem original. Páginas não reconhecidas provocam erro, sem prévia parcial silenciosa. |
| F06 | Rodapés reconhecidos pela estrutura “Página N de M”; “Design de páginas web” deixa de ser descartada. |
| F07 | Grid base antes das media queries; uma coluna até 375 px, duas até 1100 px e três acima disso. Corrigido também o menu que excedia a tela de 320 px. |
| F09 | README diferencia homologação histórica da execução atual; novos resultados documentados aqui. Automação em CI continua pendente. |
| R03 | Banco copiado para `C:\Users\jeanm\PlanoDados\data\plano.db`, com comparação de todas as tabelas antes da ativação. Original preservado. Configuração aponta para a cópia verificada, sem banco vazio. |
| R05 (parcial) | Limite de 100 páginas antes da extração textual. OCR mantém 12 páginas por documento e timeout de 90 segundos. Isolamento/timeout global para a extração textual ainda pendente. |

O iniciador foi aberto com o banco dedicado. `python_path` aponta para o Python local com as dependências já instaladas; `run.ps1` agora respeita essa configuração, como o executável já fazia.

## Importações reais

Os três PDFs da pasta `dowloads` foram relidos, sem inserir ou substituir cadastros pessoais:

- Eletrotécnica: 26 componentes, 1.220 horas, nenhuma linha bloqueada.
- Engenharia da Computação: 19 componentes únicos, 735 horas; 57 repetições reunidas entre quatro páginas.
- Engenharia Elétrica: 19 componentes únicos, 735 horas; 57 repetições reunidas entre quatro páginas.

Essas quantidades descrevem os arquivos, não os cursos completos anteriormente complementados com fontes oficiais. Evidência: `real-pdfs.json` na pasta do backup. PDF misto foi validado com fixture textual real e resposta OCR simulada; ainda falta homologar OCR real em um PDF misto representativo.

## Próximas etapas, em ordem

1. **Concorrência e idempotência (F04/F08): concluída em 30/10/2026.** Detalhes e evidências abaixo.
2. **Segurança e armazenamento (R01/R02/R04/R05/R06):** testes de origem e cabeçalhos, política de diagnóstico, orçamento global do parser e comparação incremental de cópias.
3. **Acessibilidade restante:** teclado completo, zoom, contraste, leitor de tela e gráficos; as verificações responsivas acima não equivalem a certificação WCAG.
4. **Desempenho/automação:** benchmarks em bancos sintéticos grandes, logs sanitizados, dependências reproduzíveis e relatório vinculado à versão. A contagem de testes documentada é da execução datada, não uma garantia permanente.
5. **Evolução de produto:** propostas G01–G14 são opcionais; priorizar conforme uso, mantendo planejamento inativo e sem expandir projetos indiscriminadamente.
6. **Entrega final:** pacote limpo, instalação/upgrade em cópia, backup externo e reinício completo do Windows. Reinício não foi realizado automaticamente.

Não são entregues neste lote sincronização, autenticação, backup automático, instalador portátil ou proteção de reenvios de todas as operações do sistema.

## Etapa 2 entregue — concorrência e reenvios

- Migration nova `0008_catalog_concurrency`; migrations 0001–0007 não foram editadas.
- Cursos e disciplinas exigem `version` inteiro atual nas edições, no arquivamento e na restauração. Cada escrita incrementa a versão. Conflitos retornam 409 e a lista é recarregada; o formulário preserva o texto digitado e orienta fechar/reabrir para conferir.
- Atualização por importação exige `expected_id` e `version` da disciplina identificada na prévia. Renomeações, arquivamentos ou edições posteriores impedem a sobrescrita; todo o lote é revertido em conflito.
- Registro manual e correção guardam SHA-256 do JSON canônico do pedido, excluindo somente `operation_key`. Ordem das propriedades não importa; conteúdo diferente com a mesma chave retorna 409. Ausência de campo versus campo explícito são pedidos diferentes. Reenvio idêntico retorna o registro atual sem reaplicar a escrita ou desfazer correções posteriores.
- Chaves antigas, anteriores à migration, não têm assinatura reconstruída: retornam conflito com orientação para conferir o histórico. Nenhum dado antigo foi inventado ou regravado.
- Histórico de projetos/etapas renomeados ou arquivados continua preservando os nomes originais.

Validação: **104 testes Python aprovados**, testes Edge com duas abas (curso, disciplina, arquivamento, situação rápida e importação) e regressão do relógio/recuperação/intervalos/mobile. Evidências: `C:\Users\jeanm\AppData\Local\Temp\plano-catalog-concurrency-Qi3bd1` e `C:\Users\jeanm\AppData\Local\Temp\plano-timer-controls-Oace5l`.

Aplicação no banco pessoal: servidor conferido parado; upgrade fez backup, ensaio em cópia e comparação de todas as colunas/linhas anteriores. Preservados 3 cursos, 178 disciplinas, 11 sessões finalizadas, 17 relógios, 14 tópicos e 1 projeto. Integridade OK e nenhuma violação de chave estrangeira. Servidor reaberto pelo executável e API conferida no esquema 0008.

Relatórios e backups: `C:\Users\jeanm\PlanoBackups\concorrencia-20261030-131546` (`migration.json`, `live-smoke.json`, backup anterior, cópia ensaiada e `apos-migration.db`). A tentativa inicial de encerramento foi bloqueada pela revisão automática; a aplicação ocorreu somente depois de constatar que o servidor já estava parado.

Próxima etapa: segurança e confiabilidade do armazenamento (item 2 da lista acima). A auditoria integral permanece em andamento.
