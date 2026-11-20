# Conectividade e protagonismo estrutural das entidades

A análise distingue diversidade de conexões, frequência relacional e posição na estrutura dirigida. As métricas usam o mesmo universo de grupos de entidades da rede versionada; não mesclam grupos nem alteram as relações.

## Medidas e convenções

| Coluna | Definição |
|---|---|
| `neighbor_degree` | Número de entidades vizinhas distintas, ignorando direção e rótulo. |
| `neighbor_degree_centrality` | Número de vizinhos dividido por N−1, na projeção simples. |
| `in_neighbors`, `out_neighbors` | Número de vizinhos distintos em cada direção. Um vizinho recíproco pode aparecer nas duas contagens. |
| `in_typed_degree`, `out_typed_degree` | Número de arestas tipadas agregadas em cada direção. Diferentes rótulos para o mesmo par podem contar separadamente. |
| `typed_degree` | Soma dos graus por arestas de entrada e saída. |
| `in_strength`, `out_strength` | Soma dos pesos das arestas em cada direção. |
| `weighted_strength` | Soma das forças de entrada e saída. |
| `pagerank` | Escore ponderado dirigido, na escala nativa do GDS. |
| `pagerank_share` | Escore dividido pela soma dos escores observados, para expressar participação relativa. |

O peso é a quantidade de registros relacionais agregados. Não representa número de notícias distintas: várias relações da mesma notícia podem participar da força. A soma das forças de entrada e das forças de saída deve coincidir, separadamente, com a soma dos pesos. A soma das forças totais é o dobro dessa soma. Analogamente, os graus por arestas somam 2M dirigido, enquanto o número de vizinhos soma duas vezes o número de pares não dirigidos.

`mention_count`, `distinct_news_count`, `relation_news_count` e indicadores de qualidade dos grupos permanecem junto às métricas. `distinct_news_count` refere-se à presença da entidade nas menções NER selecionadas; `relation_news_count` conta notícias que sustentam sua participação na rede de relações. São coberturas distintas.

## PageRank ponderado

Utiliza-se a projeção GDS dirigida validada, com `relationshipWeightProperty='weight'`, amortecimento 0,85, limite de 100 iterações, tolerância 1e-7 e quatro trabalhadores internos do GDS. A intensidade de cada conexão pondera a contribuição transmitida nas relações de saída. Relações tipadas paralelas são preservadas e seus pesos contribuem proporcionalmente.

O cálculo usa `stream`, precedido de estimativa de memória. Não grava propriedades no Neo4j, não cria outra projeção e não realiza chamadas NER ou RE. Não se assume que os escores nativos somem um ou N. A coluna de participação relativa é uma transformação explícita; ela não deve ser confundida com a distribuição estacionária de uma variante que redistribui a massa de vértices sem saída.

A referência independente implementa a recorrência na escala nativa: contribuição básica 1−α por nó e soma das contribuições recebidas α·r(origem)·peso/força de saída. Nós sem saída não redistribuem sua massa. A referência itera até mudança máxima menor que 1e-12, com limite de 1.000 iterações. Todos os escores GDS são comparados à referência, com tolerâncias numéricas registradas (`rtol=1e-5`, `atol=1e-5`). Esse confronto numérico não é uma avaliação semântica das relações extraídas.

O modo GDS `stream` não retorna `didConverge` ou quantidade de iterações realizadas. Esses campos não são inventados: registram-se os parâmetros, tempos, versão GDS, valores obtidos e divergências perante a referência local convergida. O algoritmo não é repetido em `stats` apenas para obter esses campos.

## Interpretação

Uma entidade pode ter muitos vizinhos e poucas repetições relacionais, ou poucos vizinhos e relações frequentes. PageRank também depende da posição das entidades que apontam para ela. Comparar essas medidas ajuda a diferenciar formas de protagonismo estrutural.

Os rótulos semânticos têm direções próprias. Receber uma relação de localização, por exemplo, não significa exercer influência sobre o emissor. Por isso, o PageRank conjunto das relações heterogêneas é uma caracterização estrutural, condicionada à representação escolhida. Não estabelece prestígio, poder, causalidade ou influência social. Análises futuras por família relacional podem investigar a sensibilidade dos resultados à direção e à composição das relações.

Extração incompleta, distribuição desigual de notícias entre fontes e anos, decisões de resolução de entidades e grupos ainda sujeitos a revisão condicionam os rankings. Nomes parecidos não são unificados nesta etapa; a chave analítica é `entity_group_id`. Homônimos podem ser grupos diferentes, e variantes ainda não agrupadas podem fragmentar a frequência de uma entidade real.

## Rankings, figuras e correlações

As tabelas mantêm todos os nós. Os rankings exibem os 20 primeiros, globalmente e por tipo, para quatro medidas: vizinhos, grau por arestas, força e PageRank. A posição estatística usa empates (`rank` mínimo); a ordem visual em caso de empate usa ID crescente, sem atribuir superioridade científica ao desempate.

São geradas três figuras com os cinco primeiros de cada tipo: vizinhos, força e PageRank. As cores são pessoa `#4C78A8`, organização `#F58518` e local `#54A24B`. Cada painel possui escala própria, identificada no catálogo. Comparações entre tipos devem observar os valores dos eixos, não apenas o comprimento visual das barras.

A matriz de Spearman compara as quatro medidas e as contagens de notícias relacionais e menções. As correlações são descritivas, sem p-valores ou inferência de independência entre vértices. Correlações de colunas constantes podem ficar vazias.

## Proveniência e saídas

Resultados em `resultados/centralidades/<assinatura>/`, com apontador `atual.json` somente após validação completa:

- `centralidades_nos.csv.gz`: todos os nós, atributos, métricas e posições nos rankings.
- `rankings.csv`: seleção global e por tipo, mantendo IDs.
- `correlacoes_spearman.csv`: associação descritiva entre as medidas.
- `resumo_metricas.csv`, `execucao_gds.json`, `verificacao_pagerank.json`, `ambiente.json` e manifesto com hashes.
- Três figuras em SVG, PNG e PDF, acompanhadas de catálogo analítico.

Os IDs permitem consultar as notícias pelas tabelas de proveniência da rede ou por `consultar_noticias(projeto, entity_id=..., somente_relacoes=True)`, disponível no módulo de construção. Esta etapa não substitui as visualizações HTML com exemplos clicáveis e acesso à lista completa de notícias, que são produtos próprios da etapa de visualização dos grafos.

Uma versão completa com os mesmos dados e código é conferida e reutilizada. Alterações de entradas ou implementação geram outra versão. Betweenness, closeness, comunidades, comparação entre fontes e evolução temporal não são calculadas nesta etapa.

Referência técnica: https://neo4j.com/docs/graph-data-science/current/algorithms/page-rank/
