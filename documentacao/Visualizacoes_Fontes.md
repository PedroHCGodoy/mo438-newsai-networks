# Visualizações e evidências das comunidades por fonte

## Dados e cobertura

São utilizadas as redes por fonte e as partições persistidas e verificadas. As duas partições de apresentação são Louvain e a primeira semente Leiden configurada. As outras sementes permanecem disponíveis nos resultados científicos para análise de estabilidade.

Os painéis incluem todas as comunidades dessas duas partições. Os limites afetam somente os desenhos; não reduzem os catálogos, contagens ou listas de notícias.

## Representações

A apresentação principal utiliza pares não dirigidos com os pesos somados entre rótulos e ambos os sentidos, como na detecção de comunidades. A inspeção dirigida é complementar e utiliza as relações originais dos mesmos pares selecionados. Nenhum sentido ou rótulo é inferido pela visualização.

As vistas gerais da fonte começam com cores por comunidade. As vistas internas começam com cores por tipo de entidade. A interface permite alternar. Cores por comunidade são locais à fonte e à partição; não codificam correspondência entre fontes. O layout usa semente 42, molas com transformação log1p dos pesos apenas para apresentação e disposição separada das componentes desenhadas. As posições são persistidas.

## Suporte documental

As notícias de uma comunidade são a união das notícias que sustentam relações incidentes a seus nós. Suporte interno requer relação com ambos os extremos na comunidade; suporte de fronteira envolve relação entre comunidades. Uma notícia pode ter ambos os papéis e apoiar várias comunidades. Portanto, as contagens de suporte interno e de fronteira não devem ser somadas como conjuntos disjuntos.

Notícias são identificadas por ID e versão, e contagens distintas usam a união dos IDs. Os painéis preservam exemplos e listas completas com títulos, links, categorias, fonte, datas e autoria. Categorias são editoriais e não são atribuídas como temas automáticos de comunidades. Destaques por PageRank utilizam a rede completa da fonte, sem recalcular o escore dentro da comunidade.

## Diagnóstico de comunidades desconectadas

Todas as comunidades sinalizadas nas duas partições apresentadas recebem uma vista adicional. Uma busca independente no subgrafo induzido completo confere a quantidade de partes conexas e exporta cada membro com seu ID de parte, nome e tipo. Caminhos que passam por outras comunidades não tornam uma comunidade internamente conexa.

O limite de nós dessas vistas é configurável separadamente, com padrão 200; a vista normal usa 100. O limite de pares é compartilhado e não deve ser confundido com o conjunto integral de conexões utilizado no diagnóstico. Um desenho pode conter componentes adicionais por omissão de arestas, sem que isso altere a conectividade medida no subgrafo completo.

As partições originais são preservadas. A inspeção permite examinar entidades e notícias de cada comunidade sinalizada, mas não identifica automaticamente a causa do comportamento do algoritmo nem comprova uma interpretação temática.

## Reprodução e interpretação

Hashes das redes, partições, código visual e interface são registrados, assim como limites e versões das bibliotecas de layout. Os recursos JavaScript e CSS necessários são incluídos nos HTMLs; não há dependência de CDN ou conexão ao Neo4j para abrir os arquivos. Os links das notícias são externos e exigem acesso à web quando acionados.

Os catálogos e CSVs persistidos permitem reproduzir e ajustar a apresentação sem recalcular os resultados científicos. Os grafos exibidos são recortes explícitos e devem ser apresentados com seus limites e objetivo analítico. A organização observada depende da cobertura do corpus, das extrações e da resolução de entidades; uma figura não constitui validação semântica ou causal.
