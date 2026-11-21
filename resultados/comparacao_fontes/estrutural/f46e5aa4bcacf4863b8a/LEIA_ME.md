# Comparação estrutural

Graus, componentes e triângulos foram calculados no GDS em projeções simples não dirigidas com peso unitário e confrontados integralmente com uma implementação independente. As projeções derivam das tabelas por fonte, usando nós identificados na edição global carregada no Neo4j. Nenhum nó ou relacionamento persistente foi criado ou alterado. As projeções GDS são objetos em memória.

A reciprocidade usa pares dirigidos distintos, ignorando rótulos e pesos. Ela é a fração de pares que possuem o par reverso. Rótulos inversos e a expansão de relações podem elevar essa medida; ela não é evidência de reciprocidade social ou editorial.

A média principal de clusterização usa grau ≥ 2. A média de todos os nós inclui zeros para grau < 2. A transitividade é 3T dividido pelas triplas conectadas. A densidade é 2M/[N(N−1)]. A maior componente é escolhida por tamanho e, em empate, pelo menor ID canônico.

As diferenças de volume, composição e cobertura de RE permanecem limitações. Não se conclui que maior número de nós ou arestas implica maior diversidade, qualidade ou complexidade jornalística. As figuras de graus são descritivas; não ajustam lei de potência.
