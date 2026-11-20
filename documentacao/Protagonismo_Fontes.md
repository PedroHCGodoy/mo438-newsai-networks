# Protagonismo estrutural por fonte

## Definições

Esta etapa reutiliza as funções da análise de centralidades global, mantendo as definições e a configuração científica. A caracterização estrutural deve pertencer à mesma edição das redes por fonte.

| Medida | Definição |
|---|---|
| `neighbor_degree` | Número de vizinhos distintos, sem direção |
| `neighbor_degree_centrality` | Grau de vizinhança dividido por N−1 |
| `in_neighbors`, `out_neighbors` | Vizinhos distintos por direção |
| `in_typed_degree`, `out_typed_degree` | Quantidades de arestas dirigidas por rótulo |
| `typed_degree` | Soma dos graus tipados de entrada e saída |
| `in_strength`, `out_strength` | Somas de pesos por direção |
| `weighted_strength` | Força total de entrada e saída |
| `strength_share` | Força total dividida pela soma das forças na própria rede |
| `pagerank` | Escore nativo do GDS na rede dirigida e ponderada |
| `pagerank_share` | Escore dividido pela soma dos escores da própria rede |

Grau de vizinhança é confrontado com a seção estrutural. Somas de graus tipados devem recompor as quantidades de arestas; somas das forças de entrada e saída devem recompor os pesos. A soma das forças totais é duas vezes a soma dos pesos.

## PageRank

Usa `relationshipWeightProperty='weight'`, `dampingFactor=0.85`, `maxIterations=100`, `tolerance=1e-7` e `concurrency=4`. A execução é `stream`, sem escrita de propriedades no banco. As projeções dirigidas são construídas com as linhas das tabelas de arestas por fonte, preservando multiplicidade e pesos. Nós são identificados na edição global carregada no Neo4j.

A referência independente mantém a mesma escala nativa utilizada na análise global, incluindo seu tratamento de nós sem saída. Não é substituída silenciosamente por uma implementação com redistribuição de sumidouros ou outro vetor de normalização. Todos os escores devem concordar com a referência dentro de `rtol=1e-5` e `atol=1e-5`. Versão, configuração, estimativa, tempo e erro de comparação são registrados em `execucao_gds.json`.

A soma nativa não precisa ser 1. A coluna `pagerank_share` é uma transformação de apresentação posterior ao algoritmo: preserva as posições e soma 1 por fonte. Ela facilita descrever concentração relativa na própria rede, mas não cria uma escala universal de influência entre veículos.

## Gestão das projeções em memória

Uma única projeção desta etapa é utilizada por vez. A leitura da projeção usa `readConcurrency=1`; a configuração do algoritmo PageRank permanece a mesma. Após o retorno dos escores, a projeção exata é liberada com `gds.graph.drop`, inclusive em caso de erro durante sua criação ou uso. A liberação é restrita ao nome calculado para a fonte e edição; nenhuma busca por prefixo ou exclusão ampla do catálogo é realizada.

Dados persistentes, métricas exportadas e projeções de outras etapas não são removidos pelo módulo. Após uma falha de heap, um reinício administrativo do Neo4j pode ser necessário para restaurar o estado da JVM. Esse reinício elimina as projeções em memória, mas não os dados persistentes ou resultados exportados. A redução de uso simultâneo não substitui o dimensionamento adequado do heap.

Referências operacionais: [remoção de projeções](https://neo4j.com/docs/graph-data-science/current/management-ops/graph-drop/) e [configuração de memória](https://neo4j.com/docs/operations-manual/current/performance/memory-configuration/).

Referência da interface: [PageRank na documentação oficial Neo4j/GDS](https://neo4j.com/docs/graph-data-science/current/algorithms/page-rank/).

## Rankings e comparação

Posições usam o método `min`: entidades empatadas recebem a mesma posição. A limitação visual ou tabular ao top 20 usa escore decrescente e ID crescente, para obter uma seleção determinística mesmo em empates no limite. O catálogo dos nós permanece completo; os limites não removem entidades da análise.

Os top 20 são apresentados para o conjunto completo e por tipo. A tabela comparativa principal utiliza grau de vizinhança, força total e parcela do PageRank. A sobreposição de top 20 usa IDs das entidades e Jaccard da interseção sobre a união. Uma entidade ausente de uma rede não recebe automaticamente valor ou posição zero; a ausência deve ser tratada explicitamente ao cruzar tabelas.

Nomes canônicos iguais não são chaves. Os gráficos mostram também IDs para distinguir grupos homônimos. A interpretação das comparações depende da resolução de entidades adotada.

## Notícias de suporte

As listas completas são derivadas dos vínculos nó–notícia com `relation_participation_count > 0`, unindo `news_id` e `news_version_id` ao cadastro documental do recorte. As contagens distintas são verificadas contra `relation_news_count` dos nós. Os arquivos incluem títulos, links, autoria, categorias e estados documentais disponíveis.

Documentos com menção à entidade mas sem participação em relação retida não integram essa lista relacional. Seus vínculos permanecem nas tabelas `nos_noticias` da construção das redes. Assim, menção, participação relacional e centralidade não são confundidas.

## Reprodução e limites

As edições global, por fonte e estrutural são conferidas. Hashes dos módulos científicos e configuração são registrados. Resultados e figuras são persistidos, sem depender de variáveis anteriores do kernel; não há novas chamadas de NER/RE nem alteração dos dados globais.

As medidas descrevem a posição das entidades na representação extraída do corpus. Volumes, comprimento de textos, cobertura de extração, rótulos inversos e ruídos de resolução afetam os escores. Força não é necessariamente quantidade de fatos independentes. PageRank não demonstra influência social, causalidade ou relevância jornalística intrínseca. Betweenness, closeness, comunidades e mecanismos temporais não são inferidos nesta etapa.
