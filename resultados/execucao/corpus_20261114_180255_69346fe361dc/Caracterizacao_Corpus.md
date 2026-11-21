# Caracterização do corpus de notícias sobre inteligência artificial

## Escopo e unidade de análise

A análise descreve os 23,657 registros da base preparada. Todos foram mantidos, inclusive os candidatos a duplicidade e os textos curtos sinalizados anteriormente. Os identificadores de notícia são únicos nesta versão. As estatísticas descrevem o corpus coletado, não toda a produção dos veículos, a atenção pública ou a importância social da IA.

Base SHA-256: `69346fe361dc7a2da0537d9b3f7751882fb697d45378056617b81e11b2ec7a11`. Versão da análise: `1.0.0`.

## Fontes e períodos

| source | news | first_publication | last_publication | known_category_news | share_pct |
| --- | --- | --- | --- | --- | --- |
| CNN Brasil | 6592 | 2020-03-07 11:45:00 | 2026-06-30 23:40:00 | 6592 | 27.86 |
| Folha de S.Paulo | 12548 | 1994-02-02 00:00:00 | 2026-06-30 23:54:35 | 11890 | 53.04 |
| G1 | 4517 | 2017-07-15 12:02:03.781000 | 2026-06-30 16:10:33.659000 | 4516 | 19.09 |

Em 2025:

| source | news | observed_months |
| --- | --- | --- |
| CNN Brasil | 2087 | 12 |
| Folha de S.Paulo | 3413 | 12 |
| G1 | 2115 | 12 |

Há notícias nos doze meses de 2025 para as três fontes. Isso permite uma comparação em ano comum, mas não prova igual completude da coleta. As fontes têm início de cobertura observado diferente. A série de 2026 termina em 30 de junho; sua contagem anual não deve ser interpretada como retração em relação a 2025. Crescimentos de volume podem refletir mudanças de coleta e acesso, além de publicação editorial.

### Janelas com a mesma duração

| source | news_2025_jan_jun | news_2026_jan_jun | relative_change_pct |
| --- | --- | --- | --- |
| CNN Brasil | 953 | 1827 | 91.71 |
| Folha de S.Paulo | 1440 | 1831 | 27.15 |
| G1 | 602 | 2020 | 235.55 |

A comparação considera janeiro a junho dos dois anos. A duração equivalente evita comparar diretamente um semestre com um ano inteiro. Persistem diferenças de disponibilidade, seleção e composição editorial. A tabela de variação anual inclui a identificação do ano anterior observado, lacunas e a sinalização de 2026 parcial; seus percentuais não são estimativas causais.

## Macrocategorias editoriais

| category_grouped | news | share_pct |
| --- | --- | --- |
| ECONOMIA | 4652 | 19.66 |
| TECNOLOGIA_INOVACAO | 3832 | 16.20 |
| REGIONAL_LOCAL | 2602 | 11.00 |
| OPINIAO_COLUNAS_BLOGS | 2179 | 9.21 |
| CULTURA_ENTRETENIMENTO | 1859 | 7.86 |
| INTERNACIONAL | 1337 | 5.65 |
| POLITICA_PODER | 1323 | 5.59 |
| NEGOCIOS_EMPREENDEDORISMO | 1260 | 5.33 |
| NAO_INFORMADA | 659 | 2.79 |
| SAUDE | 650 | 2.75 |
| COTIDIANO_SOCIEDADE | 648 | 2.74 |
| EDUCACAO | 569 | 2.41 |
| CHECAGEM_DESINFORMACAO | 467 | 1.97 |
| CIENCIA | 415 | 1.75 |
| ESPORTES | 388 | 1.64 |
| EMPRESAS_PUBLICIDADE | 234 | 0.99 |
| MEIO_AMBIENTE_AGRO | 185 | 0.78 |
| TRABALHO_CARREIRAS | 147 | 0.62 |
| EVENTOS_ESPECIAIS | 87 | 0.37 |
| AUTO_MOBILIDADE_IMOVEIS | 86 | 0.36 |
| REDES_SOCIAIS | 41 | 0.17 |
| TURISMO_VIAGEM | 37 | 0.16 |

As categorias foram agrupadas pelo dicionário e incluem temas, formatos e origens, como opinião e publicidade. O termo diversidade editorial refere-se a essa distribuição, não à variedade de argumentos ou enquadramentos semânticos. As participações por fonte, ano e mês usam todas as notícias da respectiva combinação no denominador, incluindo a ausência de categoria.

A trajetória longa da Folha é apresentada separadamente para reduzir a mistura entre mudanças editoriais e entrada de outras fontes. Anos históricos com poucos registros e mudanças nas editorias exigem cautela.

### Distribuição e diversidade em 2025

| source | news | category_missing_pct | observed_macro_categories | effective_categories |
| --- | --- | --- | --- | --- |
| CNN Brasil | 2087 | 0.00 | 13 | 7.85 |
| Folha de S.Paulo | 3413 | 5.74 | 18 | 9.21 |
| G1 | 2115 | 0.05 | 17 | 5.38 |

Calculamos H = −Σ pᵢ ln(pᵢ), em nats, entre categorias conhecidas. O número efetivo exp(H) é o número de categorias igualmente frequentes que produziria a mesma entropia. Essa medida combina quantidade e equilíbrio das categorias. Não corrige automaticamente o efeito de amostragem: com mais notícias há mais oportunidades de observar categorias. A proporção de categorias ausentes e o volume por ano são apresentados junto à medida. Em anos sem nenhuma categoria conhecida, H e exp(H) ficam indefinidos, nunca iguais a zero.

## Autoria registrada

| author_status | news | share_pct |
| --- | --- | --- |
| ASSINATURA_PRESENTE | 18614 | 78.68 |
| NAO_IDENTIFICADA | 4570 | 19.32 |
| CAMPO_VAZIO | 473 | 2.00 |

O campo não contém apenas nomes de pessoas: há redações, agências, coautorias e sufixos de veículo ou localidade. Por isso, a unidade analisada é a assinatura registrada. Retiramos apenas o prefixo inicial Por, normalizamos espaços e comparamos capitalização dentro de cada fonte. Não dividimos vírgulas nem resolvemos identidades pessoais. As variantes permanecem na tabela de mapeamento.

Campos vazios e marcadores como Sem autor são categorias distintas de ausência e não entram nos rankings ou na concentração. A quantidade de assinaturas não deve ser apresentada como número de jornalistas. Diferenças entre fontes também refletem seus padrões de preenchimento.

### Assinaturas recorrentes em 2025

| source | author_signature | news | share_signed_news_pct | rank |
| --- | --- | --- | --- | --- |
| CNN Brasil | Reuters | 235 | 11.70 | 1 |
| CNN Brasil | Da CNN | 128 | 6.37 | 2 |
| CNN Brasil | Da Reuters | 109 | 5.43 | 3 |
| CNN Brasil | Do Estadão Conteúdo | 67 | 3.33 | 4 |
| CNN Brasil | Giovana Christ, da CNN | 59 | 2.94 | 5 |
| Folha de S.Paulo | Pedro S. Teixeira | 92 | 4.61 | 1 |
| Folha de S.Paulo | Gustavo Soares | 41 | 2.06 | 2 |
| Folha de S.Paulo | Nelson de Sá | 40 | 2.01 | 3 |
| Folha de S.Paulo | Gabriela Cecchin | 26 | 1.30 | 4 |
| Folha de S.Paulo | Daniele Madureira | 24 | 1.20 | 5 |
| G1 | Redação g1 | 288 | 13.68 | 1 |
| G1 | Redação g1 — São Paulo | 60 | 2.85 | 2 |
| G1 | Mel Trench, g1 | 56 | 2.66 | 3 |
| G1 | BBC | 50 | 2.37 | 4 |
| G1 | Reuters | 45 | 2.14 | 5 |

Os percentuais usam somente as notícias com assinatura presente na fonte. Os rankings preservam empates no arquivo CSV. O gráfico limita a oito unidades para legibilidade, com desempate alfabético operacional, sem atribuir superioridade a assinaturas empatadas.

### Concentração e continuidade

O índice HHI = Σ pᵢ² mede a concentração das notícias entre unidades de assinatura, usando apenas assinaturas presentes. Também são exportadas as participações das cinco e dez unidades mais frequentes e o número efetivo 1/HHI. Esses indicadores não medem concentração individual de trabalho ou especialização em IA.

A continuidade registra primeiro e último ano, número de anos com ocorrência e fração dos anos observados da fonte desde a primeira ocorrência da assinatura. Inclui 2026 parcial; intervalos não têm exposições equivalentes. Uma mesma pessoa com assinaturas diferentes pode ser contada em várias unidades, e uma unidade coletiva pode representar várias pessoas.

## Tamanho dos textos

Resumo de palavras por texto no recorte comum de 2025:

| source | news | median | mean | q25 | q75 |
| --- | --- | --- | --- | --- | --- |
| CNN Brasil | 2087 | 347.00 | 461.11 | 254.00 | 535.50 |
| Folha de S.Paulo | 3413 | 708.00 | 860.75 | 504.00 | 1036.00 |
| G1 | 2115 | 584.00 | 738.52 | 415.50 | 883.50 |

Palavras são itens separados por espaços, sem tokenização linguística. Caracteres incluem espaços e quebras de linha do texto original. As distribuições incluem todos os registros. Diferenças podem refletir gênero editorial, disponibilidade do corpo da notícia e seleção da coleta. Não equivalem automaticamente a maior profundidade jornalística.

## Figuras e interpretação

### Como o volume observado varia por período e fonte?

![Como o volume observado varia por período e fonte?](resultados/figuras/30_corpus_volume_publicacoes.png)

Contagens do corpus recebido. O ano de 2026 inclui somente janeiro a junho. Primeira observação não equivale à criação do veículo; volumes não representam toda sua produção editorial.

### Quais editorias estão mais representadas em cada fonte?

![Quais editorias estão mais representadas em cada fonte?](resultados/figuras/31_corpus_composicao_editorial.png)

Percentuais dentro de cada fonte, incluindo categorias não informadas. A comparação do corpus completo também reflete coberturas temporais distintas. As categorias agrupam temas, formatos e origens editoriais.

### Como a composição editorial muda mantendo a fonte fixa?

![Como a composição editorial muda mantendo a fonte fixa?](resultados/figuras/32_corpus_editorias_folha_temporal.png)

Percentuais por ano na Folha. Células sem ocorrências recebem zero somente em anos observados. Volumes históricos reduzidos e mudanças nas editorias limitam a comparação; a figura não mede diretamente enquadramentos temáticos.

### Quanto do corpus permite examinar assinaturas registradas?

![Quanto do corpus permite examinar assinaturas registradas?](resultados/figuras/33_corpus_cobertura_autoria.png)

Assinatura presente pode designar pessoas, coautorias, agências ou redações. Campos vazios e marcadores como Sem autor são excluídos dos rankings e das métricas de concentração.

### Quais assinaturas registradas são mais recorrentes em 2025?

![Quais assinaturas registradas são mais recorrentes em 2025?](resultados/figuras/34_corpus_rankings_assinaturas_2025.png)

Oito unidades de assinatura por fonte. Prefixo Por, espaços e capitalização são normalizados; vírgulas e sufixos de afiliação são preservados. Unidades não correspondem necessariamente a indivíduos distintos.

### Como o tamanho dos textos difere entre fontes?

![Como o tamanho dos textos difere entre fontes?](resultados/figuras/35_corpus_tamanho_textos.png)

ECDF do corpus completo e caixas de 2025. Caixas mostram quartis e mediana, com limites de 1,5 IQR; pontos externos não são exibidos nas caixas, mas permanecem nos cálculos e na ECDF. Os textos não foram truncados.

### Como a distribuição editorial varia diante da cobertura disponível?

![Como a distribuição editorial varia diante da cobertura disponível?](resultados/figuras/36_corpus_diversidade_editorial.png)

Número efetivo de categorias exp(H), com H de Shannon calculado somente entre categorias conhecidas. O volume de notícias é exibido para contextualizar a estimativa. Diferenças de amostragem e disponibilidade editorial impedem atribuir a mudança automaticamente a maior diversidade temática.

### Como os volumes se comparam em janeiro–junho de 2025 e 2026?

![Como os volumes se comparam em janeiro–junho de 2025 e 2026?](resultados/figuras/37_corpus_janelas_equivalentes.png)

Contagens entre 1 de janeiro e 30 de junho dos dois anos. Igual duração de calendário não garante mesma completude de coleta nem equivalência editorial. As diferenças são descritivas do arquivo.

## Verificações e reprodução

| verification | consistent |
| --- | --- |
| contagem_fontes_reconciliada | True |
| contagem_anual_reconciliada | True |
| contagem_mensal_reconciliada | True |
| categorias_fonte_reconciliadas | True |
| categorias_ano_reconciliadas | True |
| categorias_mes_reconciliadas | True |
| participacoes_categorias_somam_100 | True |
| autoria_particiona_corpus | True |
| autoria_anual_particiona_corpus | True |
| rankings_excluem_autoria_ausente | True |
| assinaturas_anualmente_reconciliadas | True |
| prefixo_por_normalizado | True |
| virgula_na_assinatura_preservada | True |
| marcador_sem_autor_nao_e_assinatura | True |
| vazio_separado_de_marcador | True |
| hhi_dentro_limites | True |
| hhi_limite_uniforme | True |
| concentracao_top10_maior_igual_top5 | True |
| concentracao_top10_ate100 | True |
| continuidade_anos_limitada_exposicao | True |
| categorias_efetivas_limite_superior | True |
| categorias_efetivas_minimo_um | True |
| anos_sem_categoria_diversidade_indefinida | True |
| janelas_mesmo_calendario | True |
| janelas_contagens_reconciliadas | True |
| corpus_nao_altera_base_preparada | True |

Para reproduzir somente esta análise em uma nova sessão, execute a seção 10 do notebook e as seções 11 a 14. A base preparada não é regravada. Tabelas, figuras em SVG/PNG/PDF e manifesto da execução são exportados para as pastas correspondentes. A extração de entidades e relações e os cálculos de redes não fazem parte desta caracterização.
