# Pós-processamento local de relações

## Instalação e execução

1. Aguarde o encerramento de qualquer lote RE ativo e salve o notebook.
2. Faça um backup da pasta `dados/processados/re/execucao`.
3. Extraia o conteúdo deste ZIP diretamente na pasta `PROJECT`. Os módulos de extração existentes não são substituídos. Caso já exista um arquivo de curadoria `correcoes_ids_aprovadas.json`, preserve-o e confira seu conteúdo antes de qualquer substituição: decisões adicionais devem ser mantidas.
4. Acrescente uma seção 25 ao final do notebook principal, usando o texto de `Secao_25_Posprocessamento.md`. O código mínimo é:

```python
from pathlib import Path
from re_posprocessamento import processar_re

resumo_pos_re = processar_re(Path.cwd())
resumo_pos_re
```

Execute essa seção quando o lote de RE estiver encerrado. Ela funciona em um kernel novo e não exige executar as seções 22 ou 23. Se o diretório atual não for a pasta `PROJECT`, passe o caminho dessa pasta explicitamente. O `.env` não é lido, e não há chamadas à API.

Ao terminar, envie o ZIP `Resumo_Pos_RE_...zip` indicado no console. Os valores esperados para as 61 notícias já conferidas são:

| Campo | Esperado |
|---|---:|
| documents | 61 |
| original_relations | 1481 |
| derived_relations | 1486 |
| recovered_relations_net | 5 |
| approved_id_mappings_used | 3 |
| repaired_endpoint_occurrences | 5 |
| flagged_relations | 24 |
| remaining_rejections | 0 |
| api_calls | 0 |

A revalidação técnica derivada deve mostrar 60 SUCCESS e 1 SUCCESS_ZERO. Se você já tiver executado mais notícias, os totais poderão ser maiores; novas respostas continuam sujeitas à inspeção e não terão seus IDs corrigidos automaticamente.

## Preservação e retomada

Este pacote não altera `re_execucao.py`, `re_parser.py`, prompts, respostas, validações de execução, fila, manifestos do planejamento, `.env` ou checkpoint. A configuração do filtro de anos e dos trabalhadores permanece igual.

O histórico da seção 23 continuará mostrando os três PARTIAL originais. O campo `revalidation_state`, nos arquivos derivados, registra o resultado após o reparo. Essa distinção é intencional: a resposta original do modelo continua auditável, e o checkpoint mantém a proteção contra novos envios.

A repetição com as mesmas entradas confere e reutiliza o mesmo snapshot, sem duplicar relações. Quando novas notícias forem processadas, uma nova pasta derivada será gerada, preservando a anterior. Os nomes das pastas identificam o conteúdo e as versões dos módulos usados. Mantenha as versões antigas até decidir como arquivar os snapshots ao concluir a pesquisa.

## Correções de identificadores

O arquivo `dados/processados/re/curadoria/correcoes_ids_aprovadas.json` contém três correspondências documentais aprovadas: SUCURSAL DE BRASÍLIA, Steve Jobs e Hofstadter. Elas se aplicam apenas às requisições e aos hashes de prompt registrados. Não alteram o prompt nem o identificador da menção no snapshot NER; corrigem as referências devolvidas pelo modelo na camada derivada.

Para cada relação afetada, o módulo registra o ID anterior, o ID corrigido, o extremo da relação, a menção e a justificativa. Depois aplica o mesmo normalizador e validador técnico do executor instalado e remove duplicatas que eventualmente resultem da correção.

Novos IDs desconhecidos geram candidatos por omissão de até quatro caracteres. Mesmo uma correspondência única fica para inspeção: não é aplicada automaticamente. Uma troca, inserção ou omissão maior pode ficar sem candidato por esta regra limitada. Esses casos continuam registrados. Corrigir um ID não demonstra que a semântica da relação está correta.

O módulo exige que o validador instalado reproduza o estado e as relações da execução original antes dos reparos. Divergências de versão ou identidade bloqueiam o processamento. Respostas truncadas permanecem parciais, mesmo quando alguns IDs puderem ser recuperados.

## Estados e auditoria semântica

- `original_execution_state`: estado que o executor registrou, preservado.
- `revalidation_state`: conclusão técnica depois das correções explicitamente aprovadas.
- `semantic_status=REVIEW_PENDING`: relação com alerta diagnóstico.
- `semantic_status=NOT_REVIEWED`: relação sem revisão semântica formal; ausência de alerta não significa aprovação.

Os três indicadores diagnósticos são: vínculo institucional com par diferente de PESSOA/ORGANIZACAO, ocorrência cujo destino não seja LOCAL e identidade entre tipos NER diferentes. Eles não excluem relações nem alteram rótulos. Podem sinalizar metonímia, instituições que designam locais ou erros do próprio NER. Também não detectam todo erro, como identidade indevida entre cidade e estado, ambos classificados como LOCAL.

A tabela de inspeção possui campos de decisão, novo rótulo, revisor e justificativa para uma etapa posterior de curadoria. Essa versão não ingere decisões semânticas nem aplica exclusões. Para anotar decisões, trabalhe em uma cópia separada da tabela; editar diretamente arquivos do snapshot fará a próxima conferência apontar alteração, preservando sua edição sem sobrescrevê-la.

## Saídas

Cada snapshot é salvo em `dados/processados/re/posprocessado/<identificador>/`:

- `relacoes_posprocessadas.csv.gz`: todas as relações tecnicamente aceitas, com menções, tipos, estados e alertas;
- `documentos_revalidados.csv`: cobertura e comparação por notícia;
- `correcoes_ids_aplicadas.csv`: histórico dos reparos efetivos;
- `candidatos_ids_inspecao.csv`: novos IDs suspeitos, sem aplicação automática;
- `rejeicoes_restantes.csv`: relações ainda rejeitadas tecnicamente;
- `inspecao_relacoes.csv`: relações com alertas e campos para revisão;
- `auditorias_revalidacao.jsonl`: diagnóstico técnico por requisição;
- `manifesto.json`: versão, hashes das entradas e saídas, contagens e mapas não utilizados.

O pacote de verificação fica em `resultados/re/Resumo_Pos_RE_...zip`. Ele não inclui o `.env`, o checkpoint, os prompts ou as respostas completas da API. Contém menções e metadados das notícias que precisam ser considerados ao compartilhar dados.

Esta etapa ainda não integra os resultados de RE reaproveitados, não aplica resolução de entidades, não expande relações e não agrega pesos. Essas operações serão realizadas na consolidação posterior. As tabelas do executor continuam representando a camada original; na consolidação, os resultados tratados devem ser selecionados explicitamente e não somados de novo aos originais.

## Verificações locais

As dependências são as já utilizadas no projeto: `pandas`, `re_execucao.py` e `re_parser.py`. Testes sintéticos, sem rede ou credenciais:

```python
%run testar_re_posprocessamento.py
```

A entrega foi validada sobre as 61 notícias fornecidas, verificando recuperação de cinco relações, preservação dos 24 alertas, imutabilidade das entradas, manutenção do checkpoint de teste e repetição sem duplicatas. A avaliação semântica continua separada da conclusão técnica.
