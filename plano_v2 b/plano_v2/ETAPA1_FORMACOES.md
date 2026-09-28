# Plano — Etapa 1: Formações

Implementação sobre o projeto enviado em `plano_v2 (2).zip`, com o importador e os dados existentes reaproveitados. A referência visual é o conjunto de seis telas aprovado em 28/09/2026. Esta entrega implementa somente Formações e a estrutura visual inicial.

## Executar

No Windows, dentro da pasta `plano_v2`, execute `./setup.ps1` se ainda não houver ambiente Python, depois `./run.ps1`. Abra http://127.0.0.1:5051/formations. A página inicial também abre Formações.

Em outro ambiente: instale `requirements.txt` e execute `python app.py`. O aplicativo usa `instance/plano.db`, ou o caminho explicitamente configurado em `PLANO_DATABASE_PATH`.

O ZIP inclui o banco da versão disponibilizada nesta conversa: 3 formações e 176 itens curriculares. Não é uma sincronização com alterações posteriores feitas no computador do usuário. Para usar um banco local mais recente, mantenha esse banco e aplique os arquivos de código correspondentes; não substitua o banco local pelo snapshot do pacote.

## Entregue

- Interface própria de Formações: cursos na coluna esquerda, grade à direita, cores e hierarquia baseadas na referência.
- Sem avatar, conta, login ou botão de PDF no cabeçalho global.
- Importação disponível dentro de Formações; prévia editável antes da gravação.
- Nova formação e disciplinas confirmadas na mesma transação. Erro numa linha cancela toda a gravação.
- Confirmação repetida para mesma formação/instituição não cria outra formação.
- Reimportação de grade existente ignora duplicidades por padrão; atualização exige escolha explícita na prévia.
- Cadastro manual de formação e disciplina, edição de nomes, instituição, modalidade, período, carga curricular, ordem, situação e datas.
- Pesquisa por formação e disciplina sem acentos e com foco preservado ao digitar; filtro de situação.
- Períodos e seções/módulos já cadastrados exibidos em grupos recolhíveis, com progresso acadêmico.
- Situação acadêmica alterada diretamente na grade. Não depende de tópicos, dificuldade, domínio, esforço pessoal ou geração de plano.
- Progresso calculado por disciplinas concluídas/dispensadas; não usa horas estudadas. Cabeçalhos de seção não entram no denominador.
- Modal não fecha ao clicar ou arrastar fora; descarte de edição exige confirmação. Navegação por teclado e estilos responsivos incluídos.
- Atualização entre abas da nova tela através de BroadcastChannel.

## Reaproveitamento e limites de arquitetura

O parser `services/grade_import.py`, validação curricular, repositórios, banco e migrations existentes foram mantidos. A nova página não carrega `static/js/app.js` nem chama `/api/bootstrap`, que agregava estudos, recomendações, planejamento e análises.

As APIs existentes de formação, grade, edição e situação foram reaproveitadas. Foi acrescentada somente uma rota pequena de prévia/confirmar importação para criar a formação após conferência. Não houve migration nova: banco continua na versão 14.

O arquivo `services/core.py` ainda contém serviços antigos e seus imports. Não foi feita uma separação integral desse módulo nesta etapa. Rotas e telas legadas continuam no código para reaproveitamento posterior, mas não aparecem no menu da nova tela. O menu expõe apenas Formações, evitando links para etapas ainda não integradas.

O modelo antigo possui um campo compartilhado `period` para período/módulo e itens estruturais `section`. A interface respeita essa estrutura existente; não inventa uma hierarquia período→módulo que o PDF/banco não tenha informado. Uma modelagem independente de módulos pode ser feita numa etapa posterior se necessária.

## Arquivos alterados/criados

- `app.py`: registra as rotas de importação inicial.
- `routes/pages.py`: página inicial e `/formations` usam a nova tela.
- `routes/formation_import.py`: prévia sem escrita e confirmação transacional.
- `templates/formations.html`: estrutura visual sem dependência do frontend legado.
- `static/css/formations.css`: estilos locais e responsividade.
- `static/js/formations.js`: listagem, grade, edição e fluxo de importação.
- `tests/test_formations_redesign.py`: sete testes de regressão do fluxo novo.
- `VALIDACAO_ETAPA1.json`: resultado dos três PDFs reais e integridade.
- `ETAPA1_FORMACOES.md`: este relatório.

## Verificação executada

Comando: `python -m unittest tests.test_formations_redesign tests.test_curriculum_import tests.test_formations tests.test_curriculum_management -q`.

Resultado: 27 testes contabilizados, 25 aprovados e 2 ignorados por fixtures antigas ausentes nos caminhos esperados pelos testes existentes. Nenhuma falha. Validados rollback, confirmação obrigatória, repetição, preservação de conclusão na reimportação, histórico acadêmico e alteração de situação sem criar estudo/plano. JavaScript passou em `node --check`.

Além da suíte, os três PDFs reais foram enviados às novas rotas de prévia e confirmação em banco temporário:

| PDF | Linhas reconhecidas | Disciplinas salvas |
| --- | ---: | ---: |
| Engenharia da Computação — UNINTER | 76 | 76 |
| Engenharia Elétrica Semipresencial — UNINTER | 76 | 75 |
| Cronograma T14 RS — Eletrotécnica | 26 | 26 |

A linha não selecionada da grade elétrica foi respeitada. No PDF de Computação, quatro disciplinas vieram sem período; no cronograma técnico, uma veio sem período. Esses campos podem ser corrigidos na conferência. O parser técnico extraiu 1.220h para um total declarado de 1.200h e mantém esse aviso visível; não foi adivinhada uma correção.

Integridade do banco enviado: `ok`, nenhuma violação de chave estrangeira. As contagens do banco do usuário permaneceram iguais às anteriores; testes que gravam usaram bancos temporários.

## Validação pendente

Não foi possível validar a interface em navegador neste ambiente. O download do Chromium não entregou um arquivo utilizável, e o navegador remoto bloqueou o servidor local com `ERR_BLOCKED_BY_CLIENT`. Não há evidência de E2E, fidelidade visual final ou responsividade conferida em navegador. Esses itens precisam de conferência local antes de considerar a etapa aprovada visualmente.

Equivalências, página de conteúdo, Hoje, cronômetro, histórico e análises ainda não receberam o novo visual. Planejamento automático não faz parte desta entrega. Não houve publicação em servidor nem alteração da instalação no computador do usuário.
