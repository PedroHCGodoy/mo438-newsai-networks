# Preparação do corpus de notícias sobre inteligência artificial

## Resultado

Base derivada: `dados/processados/noticias_preparadas.csv`.

Foram preservados 23,657 registros e os 12 campos originais. Não houve exclusões. As informações normalizadas são campos adicionais.

## Identificação documental

- `news_id`: identidade operacional baseada em fonte, URL e publicação normalizada. Datas distintas em uma URL permanecem distintas.
- `content_hash`: hash do título, descrição e texto integral originais.
- `text_sha256`: hash somente do texto integral original.
- `news_version_id`: identidade da notícia combinada ao hash do conteúdo; permite detectar mudança textual.
- `record_id`: hash de todos os campos originais, para rastrear o registro de entrada.

São strings SHA-256, não números de linha. A ordem dos registros não define os identificadores. A regra é conservadora: não resolve automaticamente equivalências entre URLs ou republicações. Alterar um metadado que integra a identidade pode exigir reconciliação explícita. Os checkpoints de extração também deverão considerar modelo, prompt e parâmetros.

## Campos derivados

| Campos | Definição |
| --- | --- |
| `source_normalized` | Fonte sem espaços nas extremidades |
| `*_date_normalized` | Data interpretada no calendário local, sem alterar a entrada |
| `*_date_status` | INTERPRETADA, FORMATO_NORMALIZADO, AUSENTE ou NAO_INTERPRETAVEL |
| `*_date_precision` | DIA, DATA_HORA ou NAO_INFORMADA |
| `*_date_timezone_status` | EXPLICITO ou NAO_INFORMADO no valor original |
| `text_length_chars` | Número de caracteres do texto original, incluindo espaços |
| `text_length_words` | Número de itens separados por espaços no texto original |
| `category_grouped` | Macrocategoria editorial ou marcador de ausência/mapeamento |
| `category_mapping_status` | MAPEADA, NAO_INFORMADA ou SEM_MAPEAMENTO |
| `publication_year`, `publication_month` | Ano e mês no calendário de publicação adotado |
| `flag_*` | Situações para inspeção; não implicam exclusão |

Nos campos normalizados, datas com fuso explícito foram convertidas para São Paulo. Datas sem fuso mantêm o horário informado; não é atribuído um fuso a elas. Datas com precisão diária continuam sem horário. Essas colunas servem à análise de calendário, não representam uma série universal de instantes UTC.

## Datas

| status | noticias | campo |
| --- | --- | --- |
| INTERPRETADA | 23657 | publication_date |
| FORMATO_NORMALIZADO | 14 | publication_update_date |
| INTERPRETADA | 23643 | publication_update_date |
| INTERPRETADA | 23657 | scraping_date |

Foram normalizados 14 formatos de atualização. Permanecem sinalizados 3 registros com dia de atualização anterior ao da publicação. Nenhuma data foi corrigida por suposição.

## Macrocategorias

| situacao | noticias |
| --- | --- |
| MAPEADA | 22998 |
| NAO_INFORMADA | 659 |

O agrupamento utiliza o dicionário de categorias e não classifica o conteúdo das notícias por modelo de linguagem. Há 22 valores observados em `category_grouped`, incluindo os marcadores de ausência. A composição mistura temas e editorias de formato/origem; deve ser interpretada como organização editorial.

## Verificações

| verificacao | consistente |
| --- | --- |
| numero_registros_preservado | True |
| todos_campos_originais_preservados | True |
| arquivo_original_preservado | True |
| record_id_unico_nesta_base | True |
| news_id_unico_nesta_base | True |
| news_version_id_unico_nesta_base | True |
| noticias_macro_reconciliadas | True |
| categorias_preenchidas | True |
| contagem_caracteres_reconciliada | True |
| contagem_palavras_reconciliada | True |
| identidade_independente_ordem | True |
| mudanca_textual_invalida_versao | True |
| mesmo_link_datas_diferentes_nao_fundidas | True |
| normalizacao_pontos_equivalente | True |
| data_inexistente_nao_corrigida | True |
| horario_fuso_convertido_calendario | True |
| data_diaria_preserva_precisao | True |
| csv_preserva_registros_e_campos_originais | True |
| csv_preserva_identificadores | True |

## Proveniência e reprodução

Entrada SHA-256: `5e83a80971e1f3b865b5236eb1563664540093eb0f51777c99ef3e2af23c81f7`.

Saída SHA-256: `66fcec5a4170666b2c80f09690a4c8f76a6b84f1858bc2fd664b588751c049d6`.

Versão da preparação: `1.0.0`. Versão da identidade: `news_identity_v1`.

O manifesto em `resultados/execucao/` registra regras, ambiente, código e hashes. O notebook pode recriar a base a partir dos arquivos originais. Os duplicados e textos curtos permanecem na base; não foram aplicadas seleções científicas ou executadas extrações de entidades e relações.
