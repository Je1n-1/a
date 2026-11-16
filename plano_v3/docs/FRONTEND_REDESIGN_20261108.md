# Plano V3 — frontend implementado em 08/11/2026

Implementação local baseada nas cinco imagens de `PACOTE_FRONTEND_PLANO_V3.zip` e no roteiro que acompanha o pacote. O site foi atualizado no checkout existente, sem framework novo, servidor externo ou alteração do banco.

## 1. Resultado por aba

| Área | Implementado |
|---|---|
| Navegação e tema | Cabeçalho horizontal único, ordem Hoje → Disciplinas → Objetivos → Projetos → Análises, estado ativo azul, ícones SVG locais, seletor de tema e acesso ao armazenamento. No celular a faixa de navegação continua no topo e pode ser deslizada. |
| Claro/escuro | Paletas semânticas para campos, tabelas, diálogos, estados, gráficos e ações. Escuro inicial; preferência persistida. Inicialização antes do CSS, compatível com CSP, sem reload. Armazenamento indisponível/inválido não impede o site. |
| Hoje | Relógio em painel próprio, anel coral, indicadores reais de hoje/semana, seleção de disciplina/projeto, sugestões existentes, disciplinas em andamento e registros recentes. Contagem contínua preservada, com pausa curta e intervalo separados. |
| Disciplinas | Indicadores do curso selecionado, cursos em faixa horizontal, busca e situação, linhas de disciplinas que viram cartões no celular. Blocos da grade mantidos; navegação pelos blocos em seção expansível. Importação, edição, arquivamento e tópicos preservados. |
| Objetivos | Caminhos em lista com linha vertical, indicadores de afazeres, seleção e resumo lateral. Detalhe completo de etapas, requisitos, revisão e vínculos preservado. Fluxo de IA externa/JSON, rascunhos e edição por diálogos mantido. |
| Projetos | Grade de cartões técnicos com SVG genérico, estado, curso, descrição, progresso real das etapas e tempo registrado. Indicadores dos projetos não arquivados. Ações de trabalho, detalhes, edição, etapas, registro manual e histórico preservadas. |
| Análises | Indicadores existentes, filtros completos, dois gráficos com paleta consistente, escala vertical em minutos e legenda no gráfico diário. Distribuição por atividade/curso/conteúdo, histórico completo, paginação, CSV, correção e auditoria preservados. |

Os indicadores de Disciplinas consideram o curso selecionado, antes dos filtros de texto/situação. Concluídas e dispensadas contam como progresso acadêmico. Os indicadores de Objetivos usam a lista exibida (ativa ou arquivada); os de Projetos usam somente os não arquivados, independentemente do filtro da lista. Não se somam horas de diferentes objetivos, pois seus vínculos podem se sobrepor.

## 2. Arquivos alterados e motivo

Caminhos abaixo são relativos a esta pasta `plano_v3`.

| Arquivos | Motivo |
|---|---|
| `templates/base.html` | Cabeçalho horizontal único, tema, ícones e carregamento de estilos compartilhados/página. |
| `templates/today.html`, `subjects.html`, `objectives.html`, `projects.html`, `analytics.html` | Composição das cinco telas, mantendo os IDs usados pelos módulos existentes. |
| `static/css/tokens.css` (novo) | Cores semânticas dos dois temas, raios, tipografia e largura comum. |
| `static/css/app.css` | Refatoração do layout e componentes; remoção da arquitetura antiga de sidebar. |
| `static/css/operations.css` (novo) | Estilos compartilhados de diálogos, importação, tópicos, recuperação e aviso de intervalo. |
| `static/css/today.css`, `static/css/subjects.css` (novos) | Estilos específicos de Hoje e biblioteca, extraídos do antigo arquivo global e redesenhados. |
| `static/css/objectives.css`, `projects.css`, `analytics.css` | Layout e responsividade das outras três abas, com as mesmas variáveis visuais. |
| `static/icons.svg`, `static/js/icons.js` (novos) | Conjunto SVG local reutilizável, sem requisições externas. |
| `static/js/theme-init.js`, `static/js/theme.js` (novos), `static/js/shared.js` | Inicialização, alternância, persistência e sincronização da preferência visual. |
| `static/js/today.js`, `subjects.js`, `objectives.js`, `projects.js`, `analytics.js` | Markup dinâmico, indicadores derivados dos dados já carregados, ícones e escala visual dos gráficos. Sem novos endpoints ou mudanças de regra de negócio. |
| `tests/browser_frontend.cjs` (novo) | Banco e servidor temporários próprios, testes das cinco telas, fluxos funcionais, temas, contraste de tokens e capturas. |
| `tests/browser_objectives.cjs` | Espera explícita pela navegação para o detalhe antes de testar Voltar. Corrige a corrida observada no baseline. |
| `docs/FRONTEND_REDESIGN_20261108.md`, `docs/frontend-20261108/` (novos) | Relatório e evidências visuais/de testes. |

`app.py`, `tracker/`, `migrations/`, `config.local.json`, `run.ps1`, `Plano.exe` e o launcher não foram alterados. Nenhuma biblioteca adicionada. IDs e contratos das APIs preservados.

## 3. Validação realizada

### Antes das alterações

- Branch `refactor/study-tracker-v3`, HEAD `8d4a0ac495e1fc57d50197ce8bc21c68d1d3d3bd`, checkout inicialmente limpo.
- Cópia de segurança de código: `C:\Users\jeanm\PlanoBackups\frontend-20261108\fontes-antes.zip`.
- 120 testes Python aprovados.
- Suites isoladas de timer/tópicos, concorrência de catálogo e segurança aprovadas.
- Suite de objetivos falhou no teste Voltar: a chamada acontecia antes de o clique terminar sua navegação assíncrona. Foi adicionada espera pelo detalhe visível e pela URL. A suite passou após o ajuste, sem mudança de regra da aplicação.
- Capturas de baseline das cinco páginas em 390 e 1440 px.

### Depois da implementação

- **120 testes Python aprovados** novamente.
- `browser_timer_topics.cjs`: estudo e revisão por tópico, recarregamento, recuperação com horário de corte, pausa/retomada, intervalo programado, finalização e descarte que preserva histórico; aprovado.
- `browser_catalog_concurrency.cjs`: edições concorrentes, arquivamento desatualizado, mudança rápida de situação, importação desatualizada e nova tentativa válida; aprovado.
- `browser_objectives.cjs`: criação por IA/JSON, edição, rascunho após reload, conclusão, revisão, origem vinculada, revisão do caminho, filtros, arquivamento e navegação; aprovado.
- `browser_security.cjs`: origem hostil bloqueada, fluxo legítimo de backup/recuperação em banco de teste e CSP; aprovado.
- Novo runner de frontend executado a cada etapa e no final: **5 páginas × 2 temas × 6 larguras** (360, 390, 768, 1024, 1440 e 1920), sem overflow geral.
- Projetos pela interface: criar, editar, adicionar/concluir etapa, registrar trabalho manual, conferir anotação, abrir seleção do relógio e filtrar concluídos; aprovado.
- Análises pela interface: total exibido comparado à API, página seguinte/anterior, CSV com todos os registros (não apenas a página), correção de nota com motivo sem mudar o tempo, auditoria, filtro por projeto, agrupamento por etapa e persistência na URL; aprovado.
- Tema: persistência, valor inválido, armazenamento indisponível, troca por teclado, campos preenchidos preservados, troca com timer em execução sem alterar ID/versão/estado, navegação para outra página com sessão ativa; aprovado.
- Diálogo manual a 360 px nos dois temas, Escape e skip link para o conteúdo; aprovado.
- Estados sem resultados em Disciplinas/Projetos, período vazio em Análises e erro 503 simulado com recuperação pelos filtros; aprovado.
- Console: nenhum `pageerror`; nenhuma solicitação externa; nenhuma violação CSP nos testes finais.
- Oito pares de cores semânticas por tema medidos: todos acima de 4,5:1. Incluem texto, texto secundário, placeholder, ação primária e mensagens. Isso é uma verificação objetiva de componentes, não uma certificação integral de acessibilidade ou teste com leitor de tela.
- Conferência visual das capturas desktop/mobile, temas e diálogos.
- Cinco rotas do site real, após reiniciar: novos templates presentes e sem erros JavaScript; navegação de conferência somente leitura.

Os scripts históricos `browser_phase*.cjs`, `browser_intervals.cjs`, `browser_pdf_ocr.cjs`, `browser_projects.cjs`, `browser_rest_topics.cjs`, `browser_subject_priority.cjs`, `browser_ux*.cjs` dependem de servidores, portas, arquivos e bancos de verificação fixos de sessões anteriores. Não foram executados como se fossem suites autônomas, nem redirecionados ao banco pessoal. Os resultados acima identificam exatamente as suites executadas. A transcrição/OCR dos três PDFs originais não foi refeita nesta tarefa de frontend; parser, regras de importação e testes Python correspondentes permanecem inalterados.

### Preservação dos dados

Todos os testes que criam ou alteram registros usaram bancos temporários isolados. Nenhuma inicialização, migração ou substituição do banco pessoal foi executada.

Foi feita comparação somente leitura do conteúdo das **15 tabelas pessoais antes e depois da reinicialização**: mesmas colunas, quantidades e hashes. Integridade e chaves estrangeiras verificadas. Configuração idêntica ao SHA-256 registrado antes da implementação. Não havia sessão ativa no instante da reinicialização e o estado continuou sem sessão. O teste de troca de tema com sessão ativa foi feito separadamente em banco isolado.

O comando automático que combinava parada e abertura foi bloqueado pela revisão automática com “blocked by policy”. O usuário fechou o processo; a abertura do launcher foi feita depois, com janela oculta, e a versão atual foi conferida. Não houve encerramento forçado de sessão de estudo.

## 4. Adaptações das referências e limites

- Não foram inventados usuário autenticado, notificações, busca global, prazos, metas semanais ou calendário. O espaço do cabeçalho oferece tema e armazenamento, que funcionam.
- Hoje continua um cronômetro contínuo. Não foi convertido em Pomodoro, nem recebeu metas de concentração inventadas.
- A grade acadêmica permanece organizada pelos módulos existentes. Indicadores de conclusão são situações reais; não são porcentagens fictícias de domínio.
- Objetivos usa os próximos afazeres e requisitos existentes, sem prazos artificiais. O resumo lateral dá acesso ao objetivo completo. Nenhuma integração automática com IA foi adicionada.
- Projetos usa ilustração técnica SVG genérica, em lugar das fotos aspiracionais. Não há novas capas pessoais, anexos ou kanban fictício.
- Análises mantém os dois gráficos úteis do produto, sem repetir informações em tendências, heatmaps ou streaks sem suporte. Os horários e somas continuam com as regras existentes, inclusive sessões que cruzam datas.
- A escala vertical mostra minutos; o maior valor diário define a escala (mínimo de 1 minuto para o estado vazio). As barras usam o mesmo denominador dos rótulos. Não altera os valores retornados pela API.
- No mobile, o menu superior e o histórico possuem rolagem horizontal própria. A página inteira não transborda.
- Validação de navegador feita com Microsoft Edge/Chromium instalado. Outros motores, leitores de tela e celular físico não foram testados.

## 5. Abrir e conferir no Windows

1. Abra `C:\Users\jeanm\OneDrive\Desktop\repositório_site_estudos\a\plano_v3\Plano.exe` com duplo clique.
2. Acesse **http://127.0.0.1:5054/**. Se uma aba ainda mostrar recursos antigos, use **Ctrl+F5**.
3. Alterne o tema pelo sol/lua no cabeçalho. Navegue pelas cinco abas; seus registros existentes continuam no banco configurado.
4. A alternativa de terminal continua `powershell -ExecutionPolicy Bypass -File .\run.ps1`, executada na pasta do projeto. Não é necessário executar setup ou criar outro banco.

Para repetir a validação isolada:

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:PLANO_TEST_PYTHON='C:\Users\jeanm\AppData\Local\Programs\Python\Python313\python.exe'
python -m unittest discover -s tests -v
node tests/browser_frontend.cjs --phase=final
node tests/browser_timer_topics.cjs
node tests/browser_catalog_concurrency.cjs
node tests/browser_objectives.cjs
node tests/browser_security.cjs
```

O runner usa o Playwright do runtime local do Codex e o Edge instalado; imprime a pasta temporária com resultados e encerra apenas o servidor de teste criado por ele.

## Capturas e evidências

- [Galeria de antes/depois — cinco páginas, desktop e celular](frontend-20261108/galeria.html).
- [Resultado do teste final e medidas de contraste](frontend-20261108/depois/result.json).
- [120 testes Python — resultado final](frontend-20261108/final-python.log).
- [Comparação de preservação na reinicialização](frontend-20261108/restart-verification.json).
- [Falha original do teste Voltar](frontend-20261108/baseline-objectives.log).

As capturas da galeria usam dados fictícios identificados no banco temporário. Não incluem o banco pessoal ou seus registros.
