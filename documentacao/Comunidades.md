# Comunidades ponderadas e comparação de partições

## Pergunta analítica

Como os grupos de entidades se organizam em conjuntos com maior concentração de conexões internas, e em que medida essa organização é reconhecida por métodos diferentes? As comunidades são hipóteses estruturais para interpretação posterior com entidades, relações e notícias de suporte. Não recebem rótulos temáticos automaticamente.

## Projeção e métodos

Usa-se a projeção `community`, não dirigida e ponderada. Para cada par de entidades, seu peso soma os registros relacionais das duas direções e dos diferentes rótulos. Essa transformação representa intensidade de associação. A direção e a semântica original permanecem nas tabelas da rede para análise e visualização posteriores.

As arestas não dirigidas aparecem espelhadas na memória do GDS. Para as métricas locais, cada par é contado apenas uma vez. Assim, W é a soma dos pesos da tabela de pares, enquanto a soma dos pesos das adjacências espelhadas e a soma das forças dos nós são 2W.

| Configuração | Louvain | Leiden |
|---|---|---|
| Peso | `weight` | `weight` |
| Tolerância | 0,0001 | 0,0001 |
| Máximo de níveis | 20 | 10 |
| Iterações por nível | 20 | Convenção do algoritmo GDS |
| Resolução | Modularidade padrão, γ=1 | γ=1 |
| Aleatoriedade | Sem parâmetro `randomSeed` na API utilizada | θ=0,01; sementes 42, 43 e 44 por padrão |
| Concorrência | 1 | 1 |

Louvain é a partição de referência. Leiden é comparação complementar. A primeira semente configurada define a referência visual Leiden antes de observar os resultados: não se escolhe posteriormente a execução de maior modularidade. Todas as partições são preservadas.

Usa-se uma thread por execução para reduzir variação associada à execução concorrente. Isso não garante reprodução bit a bit entre versões do GDS, ordens internas de projeção ou plataformas. Não se atribui ao Louvain uma semente que sua API não oferece. As três sementes Leiden permitem uma primeira avaliação de sensibilidade, sem esgotar as possíveis soluções. Não há varredura de γ nesta etapa.

## Qualidade e conectividade

A modularidade ponderada padrão é calculada localmente para a partição efetivamente retornada:

Q = soma sobre as comunidades de [peso interno/W − (soma das forças da comunidade/(2W))²].

O peso interno conta cada par uma vez; a soma das forças conta duas vezes cada aresta interna e uma vez cada aresta de fronteira. A fórmula usa a mesma resolução, γ=1, para comparar os métodos. A interpretação se refere ao modelo de referência de modularidade, que preserva forças esperadas; não se executa aqui um ensemble de redes aleatórias.

Para cada comunidade, são registrados número de nós, pares internos, pesos internos e de fronteira, força total, densidade interna simples, composição por tipo e número de partes conexas. A condutância é o peso de fronteira dividido pelo menor volume entre comunidade e complemento. Fica indefinida quando esse denominador é zero.

A conectividade interna é verificada sobre todos os nós e pares, por união de conjuntos. Comunidades com mais de uma parte conexa são sinalizadas, inclusive quando atravessam componentes originais. Não são divididas automaticamente: fazê-lo mudaria a partição que se pretende avaliar. Essa verificação empírica é distinta das garantias teóricas dos métodos e não estabelece coerência temática.

Uma referência adicional agrupa os nós apenas por suas componentes conexas e calcula sua modularidade. Ela ajuda a perceber a contribuição da fragmentação à pontuação global; não é outro resultado de detecção, um teste estatístico ou um modelo nulo amostrado. Não se deve interpretar a diferença de Q como uma decomposição aditiva universal.

## Comparação de partições

- **ARI:** concordância corrigida pelo acordo esperado ao acaso, baseada nos pares de nós. Pode ser negativa; 1 indica partições equivalentes, independentemente dos nomes dos grupos.
- **NMI:** informação mútua normalizada pela média aritmética das entropias. Varia de 0 a 1, com convenções explícitas para partições triviais. Não possui a mesma correção de acaso do ARI.

As medidas são implementadas com contingências esparsas, evitando uma matriz densa comunidade×comunidade, e são verificadas por testes com o scikit-learn quando disponível. O módulo de análise não depende desse pacote.

Comparam-se todos os pares de execuções na rede inteira e nos nós da maior componente. Na segunda análise, as partições continuam sendo as detectadas globalmente, apenas restringidas aos nós da GCC: não há nova detecção exclusiva na GCC. A concordância global pode ser favorecida pelo acordo nas numerosas componentes pequenas. Por isso, a comparação GCC é apresentada também nas figuras.

Nenhum limiar de Q, ARI ou NMI garante validade científica. Avaliam-se conjuntamente conectividade, composição, tamanhos, sensibilidade às sementes e evidências textuais. Valores altos não autorizam afirmações de comunidades verdadeiras ou temas confirmados.

## Identificadores, atributos e notícias

Cada nó mantém `entity_group_id`. O ID canônico de uma comunidade é o menor ID de entidade nela presente. Preserva-se também o ID bruto retornado pelo GDS. IDs canônicos facilitam auditoria dentro da mesma versão; IDs iguais em partições diferentes não implicam comunidades iguais, e mudanças na rede podem alterar a identificação.

As atribuições incluem os atributos e métricas dos nós da análise de centralidades. Os cinco destaques de cada comunidade são escolhidos pelo PageRank global, com desempate por ID; não são PageRanks recalculados no subgrafo da comunidade. Indicadores de resolução e cobertura permanecem disponíveis para a interpretação.

Os IDs permitem recuperar notícias nos vínculos `nos_noticias` e `arestas_noticias` da rede. A caracterização por fontes, anos e categorias e os grafos HTML com exemplos clicáveis e acesso à lista completa de notícias são etapas posteriores. Não se somam contagens de notícias por aresta para inferir quantidade distinta de notícias de uma comunidade: é necessário unir os IDs de notícias de suporte.

## Execução, retomada e saídas

Os algoritmos usam `stream`: não gravam no Neo4j e não adicionam propriedades às projeções. Antes de executar, verifica-se a projeção ponderada inteira e estima-se a memória de cada algoritmo. Cada partição é salva com manifesto e hash antes da execução seguinte. Uma retomada verifica e reutiliza as partições concluídas, exigindo a mesma versão GDS se ainda faltarem execuções.

O modo stream não retorna contagem de níveis ou estatística de convergência. Esses campos não são inventados, e não se repete o algoritmo em `stats` apenas para obtê-los. Os parâmetros e a versão GDS ficam registrados; a modularidade local avalia a partição final obtida, sem certificar que o ótimo global foi alcançado ou que o limite de níveis foi suficiente.

Diretórios:

- `resultados/comunidades/execucoes/<assinatura>/<execucao>/`: partições e recibos para retomada.
- `resultados/comunidades/instancias/<assinatura>/`: análise completa e imutável.
- `resultados/comunidades/atual.json`: apontador para a versão completa verificada.

Saídas principais:

- `particoes_nos.csv.gz`: atribuições completas de todas as execuções, com atributos dos nós.
- `metricas_comunidades.csv.gz`: composição, pesos e conectividade por comunidade.
- `entidades_destaque_comunidades.csv.gz`: até cinco nós por comunidade, pelo PageRank global.
- `resumo_particoes.csv`: métricas globais e tempo de cada execução.
- `comparacao_particoes.csv`: ARI e NMI para cada par, nos escopos ALL e GCC.
- `referencia_componentes.json`: avaliação da partição por componentes.
- `execucoes_gds.json`: configurações, tempos, estimativas de memória e versão GDS.
- Figuras em SVG, PNG e PDF: distribuição acumulada dos tamanhos; composição das maiores comunidades; concordância na GCC.

Os resultados refletem a cobertura incompleta de extração, decisões de resolução de entidades e exclusões da rede. Atribuir significado temático requer análise das notícias e dos rótulos relacionais, além das métricas estruturais.

## Referências

- Neo4j GDS, Louvain: https://neo4j.com/docs/graph-data-science/current/algorithms/louvain/
- Neo4j GDS, Leiden: https://neo4j.com/docs/graph-data-science/current/algorithms/leiden/
- Traag, V. A.; Waltman, L.; van Eck, N. J. (2019). From Louvain to Leiden: guaranteeing well-connected communities. Scientific Reports, 9, 5233. https://doi.org/10.1038/s41598-019-41695-z
- scikit-learn, ARI: https://scikit-learn.org/stable/modules/generated/sklearn.metrics.adjusted_rand_score.html
- scikit-learn, NMI: https://scikit-learn.org/stable/modules/generated/sklearn.metrics.normalized_mutual_info_score.html
