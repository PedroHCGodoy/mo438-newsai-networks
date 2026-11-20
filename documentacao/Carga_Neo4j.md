# Carga versionada de redes no Neo4j

O módulo utiliza o modelo de grafo de propriedades e a importação por UNWIND, MATCH/MERGE e lotes, seguindo a organização das redes de entidades e relações dirigidas. Não realiza NER, RE, resolução ou agregação adicionais.

## Espaço de nomes

- `NewsAIEntity`: nó científico, identificado por `(graph_tag, entity_group_id)`.
- `NEWSAI_RELATES_TO`: relação científica, identificada por `(graph_tag, edge_id)`.
- `NewsAINetwork`: metadados de execução, identificado por `graph_tag`; não pertence ao universo de nós científicos.

O graph_tag deriva da assinatura da instância de rede. Restrições de unicidade são criadas somente para esses rótulos/tipo novos. Nenhuma restrição anterior é removida ou alterada. Esta separação permite coexistir com esquemas que imponham unicidade global sobre Entity.entity_group_id.

Uma restrição com nome já ocupado e definição incompatível provoca bloqueio, sem remoção automática. O destino que contenha elementos sem manifesto reconhecido também é bloqueado. As consultas que modificam elementos usam os rótulos/tipos novos e graph_tag explícito; não há comandos DELETE ou DROP.

## Propriedades

Nós conservam ID inteiro do grupo, nome de exibição, categoria de entidade, contagens de menções e notícias, notícias com participação relacional, fontes distintas, datas observadas, sinalização de revisão e assinatura da rede. O campo `distinct_news_count` é presença NER no recorte; `relation_news_count` é suporte relacional.

Arestas conservam IDs de origem e destino, ID da aresta, rótulo/macroclasse de relação, peso, notícias/fontes distintas, contagens de sinalizações, datas observadas e assinatura. `distance = 1 / weight` segue a transformação do pipeline de referência. Trata-se de custo de caminho derivado da frequência, não distância física ou temporal. A aplicação dessa propriedade nos algoritmos será declarada explicitamente por análise.

Os exemplos incluem até três `example_news_ids`, `example_titles` e `example_links` por elemento, ordenados deterministicamente por data/fonte/ID de notícia. Não são uma amostra estatística nem substituem a lista completa. Para os nós, exemplos usam presença NER; para arestas, suporte documental da relação. `support_table` indica a tabela de apoio com todos os vínculos. As macrocategorias e distribuições completas permanecem em tabelas normalizadas, sem reduzir cada elemento a uma única categoria jornalística.

## Execução

`executar_carga=False` prepara e valida o payload local, sem ler credenciais ou conectar ao servidor. `True` usa o mesmo `.env` do módulo de inspeção, conecta ao banco indicado e realiza a carga em lotes de tamanho configurável.

As transações de lote são idempotentes. A carga completa não é uma única transação: lotes anteriores podem persistir se ocorrer interrupção. O estado LOADING impede tratar a importação parcial como uma rede pronta. A retomada requer o mesmo payload e reconcilia os lotes com MERGE.

Ao final, todos os nós/arestas, propriedades importadas e extremos são comparados com o payload. Propriedades derivadas adicionadas posteriormente, como centralidades, podem coexistir e não são apagadas pela revalidação de uma carga COMPLETE. Alterações nos atributos importados provocam bloqueio. O peso total é reconciliado com a entrada. Não se conclui validade semântica das extrações a partir dessa validação técnica.

A identificação da rede ativa é conferida novamente antes de gerar o recibo. Assinaturas e atributos de uma edição anterior não são sobrescritos para representar entradas novas. Novas edições produzem outro graph_tag e exigem projeções próprias.

O pacote de resumo contém apenas o recibo de carga, sem credenciais. Testes sintéticos verificam controle, isolamento e retomada, mas não validam uma instalação real de Neo4j; a execução no ambiente local é necessária.

## Referências

- Transações no driver Python: https://neo4j.com/docs/python-manual/current/transactions/
- Restrições de unicidade compostas: https://neo4j.com/docs/cypher-manual/current/schema/constraints/create-constraints/
