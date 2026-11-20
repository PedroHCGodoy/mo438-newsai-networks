# Auditoria do corpus de notícias sobre inteligência artificial

Auditoria executada em 2026-11-14T17:51:50.692917-03:00. Referência temporal: 2026-11-14.

Foram lidos 23,657 registros e 12 colunas. Nenhum registro foi excluído ou corrigido. As contagens descrevem o arquivo de entrada integral, antes de qualquer seleção analítica.

## Identificação da entrada

Arquivo: `NewsAI_BR_20261114_4termos_sem_notas_editoriais_textos_recuperados.csv`. SHA-256: `5e83a80971e1f3b865b5236eb1563664540093eb0f51777c99ef3e2af23c81f7`.

## Fontes e cobertura

| fonte_auditoria | noticias | primeira_data | ultima_data |
| --- | --- | --- | --- |
| CNN Brasil | 6592 | 2020-03-07 11:45:00 | 2026-06-30 23:40:00 |
| Folha de S.Paulo | 12548 | 1994-02-02 00:00:00 | 2026-06-30 23:54:35 |
| G1 | 4517 | 2017-07-15 12:02:03.781000 | 2026-06-30 16:10:33.659000 |

## Recorte de 2025

| fonte_auditoria | noticias_2025 |
| --- | --- |
| CNN Brasil | 2087 |
| Folha de S.Paulo | 3413 |
| G1 | 2115 |

## Integridade

| verificacao | registros_sinalizados |
| --- | --- |
| titulo_vazio | 0 |
| texto_vazio | 0 |
| link_ausente_ou_invalido | 0 |
| fonte_fora_lista | 0 |
| publicacao_ausente_ou_invalida | 0 |
| atualizacao_formato_nao_reconhecido | 14 |
| atualizacao_formato_com_pontos | 14 |
| coleta_ausente_ou_invalida | 0 |
| publicacao_apos_referencia | 0 |
| publicacao_apos_coleta_dia | 0 |
| atualizacao_antes_publicacao_dia | 2 |
| tamanho_informado_invalido | 0 |
| tamanho_divergente_das_duas_definicoes | 44 |
| texto_menos_200_caracteres | 38 |

## Candidatos a duplicidade

| criterio | registros_participantes | repeticoes_alem_primeiro | grupos_repetidos |
| --- | --- | --- | --- |
| link_exato | 2 | 1 | 1 |
| link_normalizado_candidato | 2 | 1 | 1 |
| texto_exato | 34 | 17 | 17 |
| texto_normalizado | 36 | 18 | 18 |
| titulo_fonte | 126 | 81 | 45 |
| registro_integral | 0 | 0 | 0 |

Os critérios se sobrepõem. Não somar seus totais. Título repetido não implica notícia repetida. Textos iguais podem corresponder a republicações ou versões distintas. Examinar as tabelas de detalhe antes de excluir.

## Definição do tamanho dos textos

| comparacao | registros |
| --- | --- |
| coincide_com_palavras | 23549 |
| coincide_com_caracteres | 64 |
| nao_coincide_com_nenhum | 44 |

O campo `text_length` coincide predominantemente com palavras, mas também há registros coincidentes com caracteres. Por isso, uma comparação apenas com caracteres produziria um diagnóstico enganoso. Recomenda-se armazenar separadamente as contagens de caracteres e palavras e examinar os casos sem correspondência. O metadado original foi preservado.

## Cobertura parcial de 2026

Os registros terminam em 30/06/2026. A quantidade de 2026 não deve ser comparada diretamente com um ano completo como evidência de crescimento ou retração.

## Categorias

O dicionário contém 22 grupos e 774 entradas. Há 659 notícias sem correspondência e 659 categorias vazias. O mapeamento foi calculado apenas em memória e em tabelas auxiliares, preservando as categorias originais.

## Interpretação e limites

A cobertura descreve o arquivo recebido, não toda a produção dos veículos. Ausência de um ano ou mês pode decorrer da coleta ou curadoria. Não houve revisão semântica de todas as notícias, classificação de pertinência à IA, busca de duplicidades aproximadas, NER ou RE. Tamanho curto é somente um sinal. Datas fora do formato reconhecido não são necessariamente irrecuperáveis: há datas de atualização escritas como `AAAA.MM.DD`, que admitem normalização de formato em um campo derivado. A tabela de detalhe preserva os valores originais.

## Recomendações de tratamento dos dados

1. Preservar o CSV como entrada e criar a base preparada separadamente.
2. Separar identidade da notícia e versão do texto; usar hash para invalidar checkpoints quando o texto mudar.
3. Quarentenar textos ausentes, links inválidos e datas não interpretáveis quando impedirem a análise, sem apagar a entrada.
4. Não excluir automaticamente por título, texto curto, tamanho divergente ou candidato de duplicidade.
5. Revisar categorias sem correspondência e documentar o tratamento dos vazios.
   Os casos sem correspondência encontrados nesta versão são categorias vazias; não criar automaticamente uma classificação temática.
6. Para a comparação entre fontes em 2025, considerar os desequilíbrios mensais e o volume de notícias de cada fonte.
7. Usar todos os anos elegíveis disponíveis nos acumulados, preservando os dezenove marcos.

## Verificações

| verificacao | consistente |
| --- | --- |
| contagem_fontes_reconciliada | True |
| contagem_anos_reconciliada | True |
| contagem_meses_reconciliada | True |
| contagem_categorias_reconciliada | True |
| campos_originais_preservados | True |
| arquivo_original_preservado | True |
| marcos_folha_completos_na_tabela | True |

## Escopo da análise

Este relatório descreve a auditoria documental e suas verificações. Não inclui extração de entidades ou relações nem métricas de redes.
