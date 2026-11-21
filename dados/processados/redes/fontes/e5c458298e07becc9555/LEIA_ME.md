# Redes por fonte

Os prefixos cnn, folha e g1 identificam tabelas independentes. Os pesos, atributos e vínculos documentais são recontados no período de cada fonte. Os IDs globais de grupos e arestas são preservados; não compare nomes como chaves.

Os nós participam de pelo menos uma relação retida no recorte. Seus totais de menções incluem documentos do recorte com NER disponível, mesmo sem RE concluída. relation_news_count conta apenas notícias com participação nas relações retidas.

A projeção simples é não dirigida e tem peso unitário. A ponderada agrega rótulos e ambas as direções. distance=1/weight é atributo disponível, não distância topológica: caminhos em número de arestas devem usar a projeção simples.

As redes descrevem a cobertura disponível, sem imputação de relações faltantes. As mesmas exclusões da rede de origem permanecem aplicadas. Não há detecção de comunidades, cálculo de PageRank, carga ou projeção em memória do Neo4j nesta execução. As tabelas de projeção são persistidas para os cálculos posteriores.
