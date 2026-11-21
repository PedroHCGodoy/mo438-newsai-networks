# Redes acumuladas anuais

Os 32 cortes, de 1994 a 2025, integram a mesma série de análise. Os 19 marcos
de referência são uma seleção da série, sem segunda construção ou exclusão
dos anos intermediários. Cada pasta anual contém nós, arestas semânticas
dirigidas e tipadas, documentos, vínculos nó-notícia e aresta-notícia,
projeções simples e ponderadas não dirigidas e vínculos de projeção.

Os pesos e atributos são recalculados para a fonte e o período. Os nós são
extremidades de relações retidas; mention_count e distinct_news_count podem
incluir documentos com NER sem RE concluída. relation_news_count registra
suporte relacional. IDs, títulos, links e categorias preservam rastreabilidade.
Não se somam notícias distintas de arestas diferentes para estimar suporte
de uma projeção: utiliza-se a união dos identificadores documentais.

As categorias podem ser analisadas pelos vínculos documentais. Não se atribui
uma categoria editorial única a uma entidade com aparições em várias categorias.
As mesmas exclusões da rede de origem continuam aplicadas. Não há identidades,
autolaços, fusões adicionais de entidades ou imputação de relações faltantes.

Nomes e tipos canônicos utilizam a resolução compartilhada, retrospectiva.
Sua presença em um corte depende de evidência até aquele ano. A quantidade
de relações é uma contagem de registros retidos, não confiança semântica.

A cobertura é informada em todos os anos. Ausência de relações novas pode
decorrer de falta de extração; um patamar da série não demonstra estabilidade
do noticiário. Crescimento acumulado é consequência parcial da construção e
não comprova vantagem cumulativa. Mudanças de densidade e de protagonismo
serão examinadas posteriormente, considerando volume e cobertura.

As tabelas de projeção são persistentes. Nenhum grafo GDS é criado nesta
etapa. Não são calculados PageRank, comunidades, caminhos ou métricas
estruturais. A distância topológica posterior utiliza arestas unitárias;
distance=1/weight na projeção ponderada não é número de saltos.

Cada corte é instalado após gravação e validação, com hashes próprios.
Ao repetir a execução, os cortes compatíveis são conferidos e reutilizados.
Uma série só é publicada em atual.json depois da conclusão de todos os cortes.
O ZIP de conferência contém resumos e manifestos; não substitui as tabelas
completas preservadas nas 32 pastas anuais.
