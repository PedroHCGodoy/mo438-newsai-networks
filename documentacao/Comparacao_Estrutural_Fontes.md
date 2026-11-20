# Comparação estrutural entre fontes

## Representações e métodos

Graus, triângulos, componentes, densidade e clusterização utilizam a projeção simples não dirigida com peso unitário. As rotinas `redes_estrutural.executar_algoritmos`, `resumir_metricas` e `calcular_referencia` são reutilizadas para manter as definições da análise global.

As projeções por fonte são criadas por agregação Cypher `gds.graph.project`. A consulta recebe os pares das tabelas validadas, localiza seus extremos nos nós `NewsAIEntity` da edição global e projeta relações não dirigidas com peso e distância unitários. Não utiliza os pesos dos relacionamentos globais e não grava relacionamentos persistentes. As projeções recebem nomes específicos da edição e são verificadas antes de qualquer algoritmo. Se o Neo4j for reiniciado, esses objetos de memória podem precisar ser criados novamente; os resultados exportados permanecem em disco.

Referência da interface de projeção: [documentação oficial Neo4j/GDS](https://neo4j.com/docs/graph-data-science/current/management-ops/graph-creation/graph-project-cypher-projection/).

## Métricas

- Grau: quantidade de vizinhos distintos na projeção simples.
- Grau médio: `2M/N`; soma dos graus: `2M`.
- Densidade: `2M/[N(N−1)]`.
- Clusterização local: triângulos incidentes divididos por `k(k−1)/2`. Para grau menor que dois, a coluna local usa zero. A média principal considera somente grau ≥ 2.
- Transitividade: `3T` dividido pela quantidade de triplas conectadas. Sem triplas, o resultado é ausente.
- Componentes: conjuntos conexos da projeção simples; os IDs são canonizados pelo menor ID de entidade de cada componente. A maior componente é ordenada por tamanho e pelo ID canônico em caso de empate.
- Reciprocidade: pares dirigidos distintos que possuem reverso divididos pelo total de pares dirigidos distintos. Pesos e multiplicidade de rótulos são ignorados. A díade recíproca conta uma vez; o numerador de pares recíprocos conta os dois sentidos.

Os cálculos GDS de graus, triângulos e componentes são confrontados para todos os nós com a referência por adjacências, interseções e busca de componentes. Não se trata de amostragem nem substituição silenciosa do GDS. Os resultados são publicados somente se as duas implementações concordarem.

## Sobreposição

Para cada par de veículos, são comparados quatro conjuntos: IDs de entidades; pares não dirigidos; pares dirigidos; IDs de arestas dirigidas e tipadas. Jaccard é a interseção dividida pela união. As proporções direcionais de compartilhamento usam o tamanho do conjunto de cada fonte como denominador e respondem a perguntas diferentes do Jaccard.

Correspondências de entidades dependem da resolução adotada. Compartilhar pares sem direção não implica compartilhar os rótulos semânticos, sua direção, intensidade ou interpretação editorial.

## Figuras e limitações

As figuras mostram CCDFs dos graus, quatro métricas comparativas e matrizes de Jaccard para entidades e pares não dirigidos. A paleta por fonte mantém CNN azul, Folha laranja e G1 verde. Legendas analíticas são exportadas no catálogo de figuras.

O período comum controla a duração nominal do recorte, mas não iguala a quantidade e o comprimento dos textos, a seleção do corpus ou a cobertura da extração. Maior densidade ou maior clusterização não demonstram qualidade, diversidade ou complexidade jornalística superior. Relações inversas e eventuais expansões anteriores podem elevar a reciprocidade, que não deve ser interpretada diretamente como comportamento social.

Nenhum teste de lei de potência, causalidade ou mecanismo de vantagem cumulativa é realizado nesta etapa. Centralidades, comunidades e distâncias permanecem análises distintas.

## Reprodução

O manifesto registra as edições global e por fonte, hashes dos módulos reutilizados, período e concorrência dos algoritmos. A execução GDS registra versão, projeções, estimativas de memória e tempos. Dados persistentes e resultados globais são preservados; apenas o catálogo de memória recebe projeções específicas. As tabelas finais podem ser reutilizadas sem depender do estado do kernel.
