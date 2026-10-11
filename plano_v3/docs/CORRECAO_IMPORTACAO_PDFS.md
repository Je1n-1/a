# Importação dos três PDFs — 11/10/2026

Os três arquivos fornecidos em `C:/Users/jeanm/OneDrive/Desktop/dowloads` agora passam por prévia, confirmação, persistência e reimportação sem duplicar. A validação ocorreu em banco separado do pessoal.

| Arquivo | Disciplinas únicas | Carga selecionada | Leitura |
| --- | ---: | ---: | --- |
| Cronograma de Eletrotécnica | 26 | 1.220 h | Texto do PDF |
| eng eletrica.pdf | 19 | 735 h | OCR local |
| eng computacao.pdf | 19 | 735 h | OCR local |

**Limite do conteúdo fornecido:** as quatro páginas de cada PDF das engenharias repetem o mesmo trecho visível. O OCR encontra 76 ocorrências por arquivo; 57 linhas idênticas são reunidas, deixando 19 disciplinas. Isso não equivale a uma grade completa do curso. Disciplinas que não aparecem nessas páginas não são inventadas. A prévia mostra o aviso de repetição. No cronograma, as 20 h de ambientação continuam explicando a diferença entre as linhas selecionadas e o total de 1.200 h declarado.

## Implementação

- `tracker/pdf_ocr.ps1` usa o leitor PDF e o OCR em português do próprio Windows. Renderiza as páginas em memória e retorna palavras com coordenadas. O subprocesso abre sem janela.
- `tracker/pdf_ocr.py` reúne palavras na mesma altura, incluindo nome e carga em colunas separadas. Arquivos temporários são removidos após a leitura. Limites: um OCR simultâneo, 12 páginas e 90 segundos. Não envia documentos para serviços externos nem instala modelos Python.
- `tracker/grade_parser.py` continua usando texto quando disponível; aciona OCR quando uma página com conteúdo não possui texto extraível. Páginas inteiramente vazias não acionam OCR. Linhas repetidas com o mesmo nome, módulo e carga são reunidas, com aviso explícito. As linhas de OCR pedem conferência na prévia.
- `tracker/imports.py` faz a leitura do arquivo antes de consultar o SQLite. Assim, uma leitura demorada não segura o bloqueio de leitura do banco e não impede o relógio de gravar.
- `curriculum-import.js` informa o processamento e descreve o suporte a PDF em imagem. O usuário continua podendo corrigir e selecionar as linhas antes da confirmação.

O OCR requer Windows com o recurso de reconhecimento de texto em português instalado. Ele foi identificado e executado nesta máquina. Referência da API nativa: [Microsoft — OcrEngine](https://learn.microsoft.com/en-us/uwp/api/windows.media.ocr.ocrengine). Não houve alteração de schema nem novas dependências no `requirements.txt`.

## Verificação executada

```powershell
.\.venv\Scripts\python.exe scripts/check.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node tests/browser_pdf_ocr.cjs
```

55 testes automatizados aprovados. Os sete cenários adicionados verificam reconstrução de colunas, nomes/cargas/módulos e repetições, limite antes de iniciar OCR, PDF vazio, timeout/indisponibilidade e liberação do processamento, resposta inválida e gravação SQLite possível durante a leitura.

No Edge, cada arquivo foi enviado pela interface, conferido antes da escrita, confirmado e importado novamente. Resultado: 64 disciplinas em três cursos, sem duplicação. Nomes e cargas das 19 linhas de cada engenharia foram comparados com uma lista esperada independente no teste. Disciplinas homônimas de cursos distintos permaneceram separadas. Iniciar e finalizar estudo funcionou nos três cursos, produzindo três sessões de teste.

A prévia móvel foi aberta e inspecionada em 390 px, sem transbordamento horizontal da página. Não houve erro JavaScript. Evidências: `ocr-ui.json`, `ocr-tests.log`, `ocr-preview-1.png`, `ocr-preview-2.png`, `ocr-preview-3.png` e `ocr-preview-mobile.png`. O roteiro da Fase 5 foi atualizado: os PDFs das engenharias agora devem produzir prévia OCR, em vez de erro.

Na primeira execução técnica do subprocesso, o PowerShell imprimiu um resultado vazio de tarefa antes do JSON; essa saída foi suprimida antes da integração. O contrato de importação textual e a rejeição de arquivos inválidos continuam cobertos pelos testes.

## Uso e dados

Abra **Disciplinas → Importar grade**, selecione qualquer um dos três PDFs e aguarde a prévia. Confira nomes, módulos e cargas, mantenha as linhas desejadas selecionadas e confirme. Não é necessário converter esses três arquivos manualmente.

O banco pessoal não recebeu cursos ou sessões de teste. Caminhos de verificação e hashes dos PDFs estão em `ocr-environment.json`. O banco V2 e as migrations foram preservados. A versão final permanece disponível na porta 5054; o servidor de homologação é encerrado ao concluir.

Os relatórios anteriores são históricos: a limitação de OCR registrada na Fase 5 foi resolvida por esta correção. Para PDFs diferentes, especialmente capturas incompletas ou pouco nítidas, a revisão da prévia continua necessária.
