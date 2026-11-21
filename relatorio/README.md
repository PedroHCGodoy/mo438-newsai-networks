# Relatório científico: estrutura inicial

Este diretório contém uma versão de trabalho em LaTeX, com trechos
explicitamente pendentes e somente números já conferidos nas etapas
anteriores. Não é a entrega final. O texto não altera formalmente os
objetivos aprovados e não apresenta resultados da etapa de protagonismo
antes de sua validação local. A bibliografia inicial será ampliada.

## Organização e orçamento de páginas

O limite de 15 páginas será tratado conservadoramente como total,
incluindo referências. A distribuição inicial proposta é:

| Parte | Páginas previstas |
|---|---:|
| Introdução, objetivos e síntese da análise inicial | 2 |
| Fundamentação e metodologia | 3 |
| Resultados globais e comunidades | 2 |
| Comparação entre fontes | 2 |
| Evolução temporal e aprofundamentos | 3 |
| Discussão, limitações e conclusões | 2 |
| Referências | 1 |

A distribuição pode ser ajustada sem ultrapassar 15 páginas. As figuras
deverão ser selecionadas por contribuição analítica, e não por quantidade
de arquivos produzidos. HTMLs exploratórios e tabelas completas ficarão
no pacote reprodutível, sem presumir que anexos estejam fora do limite.

## Reconciliação acadêmica pendente

A proposta inicial, a orientação do professor e a apresentação parcial
não possuem exatamente a mesma redação de objetivos. A seção de objetivos
permanece explicitamente em revisão até conferir a versão formalmente
aprovada e eventuais alterações. A coleta e o processamento serão
descritos como metodologia, sem substituir contribuições científicas.

A síntese da análise inicial retoma suas três abordagens, sem reutilizar
números antigos como resultados atuais. O peso desta edição é a soma
de ocorrências semânticas retidas, e não mera coocorrência de menções.
As referências a resultados desta edição provêm dos pacotes já validados.

## Compilar

No diretório relatorio, com uma distribuição LaTeX instalada:

```text
latexmk -pdf -interaction=nonstopmode relatorio.tex
```

Também é possível importar relatorio.tex e referencias.bib em um projeto
Overleaf. A geração do relatório não acessa APIs de extração ou Neo4j.
O PDF incluído é apenas a prévia compilada deste esqueleto.
