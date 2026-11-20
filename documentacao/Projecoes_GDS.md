# Projeções para análise estrutural e comunidades

As projeções são representações analíticas derivadas. A rede dirigida multirrelacional e sua proveniência permanecem intactas nas tabelas e no Neo4j. Cada projeção seleciona exclusivamente NewsAIEntity e NEWSAI_RELATES_TO com o graph_tag da instância validada; NewsAINetwork e dados anteriores ficam fora.

## Representações

### Dirigida

Preserva uma relação em memória para cada aresta relacional agregada da rede de entrada, inclusive arestas paralelas entre o mesmo par com rótulos diferentes. Peso e distância seguem a carga, com distância igual ao inverso do peso. É a referência para análises direcionais compatíveis, como PageRank ponderado.

Como no modelo de projeção anterior, o GDS usa um único tipo técnico de relação. Os rótulos semânticos textuais, IDs de arestas e demais atributos não numéricos ficam na rede persistida e em suas tabelas. A projeção conserva a multiplicidade e os valores das arestas, sem afirmar que o catálogo GDS contém todos os atributos textuais da rede original.

### Estrutural simples não dirigida

Todas as arestas em qualquer sentido entre dois grupos são reunidas em um par não ordenado, sem autolaço. Cada par possui peso unitário e distância unitária. As análises devem usar a topologia sem ponderação. Essa é a referência para grau de vizinhança, densidade, clusterização, componentes e distâncias estruturais.

A projeção não soma arestas paralelas como se fossem vizinhos adicionais. Uma entidade ligada várias vezes à mesma entidade tem um vizinho nesse par.

### Comunidades não dirigida ponderada

A topologia é a mesma da representação estrutural. O peso de cada par é a soma dos pesos das arestas relacionais de todos os tipos e dos dois sentidos. Isso representa frequência acumulada de registros de relação no par, sem transformar frequência em intensidade social comprovada. A distância derivada é 1/peso do par; não é a soma ou média das distâncias das arestas originais. Nesta etapa ela apenas fica disponível; análises de caminhos precisam declarar sua escolha.

Louvain e Leiden ponderados poderão usar o peso do par. A comparação científica entre partições, parâmetros e critérios de qualidade será realizada em etapa própria. Não é calculada modularidade nesta etapa.

## Contagens do GDS

Uma conexão não dirigida é disponibilizada nos dois sentidos pelo GDS. Por isso, a contagem interna de relações e a soma interna dos pesos são o dobro da contagem e do peso sobre pares científicos. Não usar relationshipCount interno diretamente em fórmulas de rede simples não dirigida. Os resumos guardam ambos os significados.

Os nós das três representações são os mesmos nós participantes da rede de entrada. A igualdade do conjunto de IDs é validada, não apenas a quantidade. Não se incluem entidades do catálogo sem participação relacional e não se inferem novas relações.

## Proveniência e suporte documental

Arquivos locais versionados em `dados/processados/redes/projecoes/<assinatura>/`:

- `simples_nao_dirigida.csv.gz`: par, extremos, peso/distância unitários, número de arestas relacionais reunidas e notícias distintas.
- `ponderada_nao_dirigida.csv.gz`: par, extremos, peso somado, distância derivada, multiplicidade e suporte documental.
- `vinculos_arestas_projecoes.csv.gz`: correspondência entre edge_id da rede original e pair_id das projeções não dirigidas.
- `manifesto.json`: entrada, regras, versões, hashes, nomes das projeções e contagens esperadas.

O suporte de um par é a união dos IDs de notícias das arestas reunidas. Somar distinct_news_count das arestas originais contaria notícias repetidas. Os vínculos permitem recuperar os registros, as categorias de notícias e os exemplos/listas completas nas visualizações futuras. IDs de pares são determinísticos por extremos, independentemente do peso e do nome de exibição.

## Validação e atualização

A carga do banco precisa estar COMPLETE e corresponder ao payload da rede ativa. Os atributos importados e os extremos são conferidos novamente antes da projeção. O módulo então verifica, para cada grafo GDS:

1. Banco, quantidade de nós e quantidade interna de relações.
2. Todos os IDs de grupos e o graph_tag dos nós de origem persistidos.
3. Todos os pares direcionais, suas multiplicidades e valores de peso/distância, com tolerância numérica de 1e-12.

As consultas de criação usam a função de agregação Cypher gds.graph.project e não são retentadas automaticamente. Não há criação de rótulos temporários no banco, gravação de propriedades, remoção de dados ou descarte automático de grafos GDS. Grafos existentes só são reutilizados se passarem pelas mesmas verificações. Em caso de falha, projeções criadas podem permanecer em memória e serão verificadas na retomada.

Os nomes incluem a assinatura da instância e da especificação de projeção. Novas entradas ou mudanças de código geram outras versões; as anteriores permanecem preservadas. O recibo local identifica as projeções validadas. A presença dos grafos no catálogo deve ser conferida ao executar algoritmos, pois o catálogo em memória não é uma garantia de persistência após reinício do servidor.

memoryUsage no recibo é o valor informado pelo catálogo, não medição independente nem garantia de memória disponível para algoritmos. As estimativas específicas serão consultadas antes dos cálculos custosos. Nenhum algoritmo ou teste de qualidade semântica das extrações é executado nesta etapa.

## Referências técnicas

- Projeção Cypher: https://neo4j.com/docs/graph-data-science/current/management-ops/graph-creation/graph-project-cypher-projection/
- Catálogo: https://neo4j.com/docs/graph-data-science/current/management-ops/graph-list/
- Leitura de propriedades relacionais: https://neo4j.com/docs/graph-data-science/current/management-ops/graph-reads/graph-stream-relationships/

Os testes sintéticos e a preparação local não substituem a validação no Neo4j/GDS instalado no ambiente de execução.
