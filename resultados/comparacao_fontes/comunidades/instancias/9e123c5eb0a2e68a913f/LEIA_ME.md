# Comunidades por fonte

Projeções ponderadas não dirigidas somam rótulos e ambos os sentidos. Uma fonte por vez; sua projeção é liberada ao final. Partições completas são salvas por execução e retomadas sem nova detecção quando compatíveis. Louvain é a referência; a primeira semente de Leiden é a referência visual predefinida. Todas as partições são preservadas.

Modularidade é calculada na mesma convenção ponderada, resolução 1; a partição por componentes é referência de fragmentação, não teste contra modelo nulo. ARI/NMI dentro da fonte usam toda a rede e a restrição à maior componente de partições detectadas globalmente. Entre fontes, usam somente entidades comuns.

Correspondências são os melhores candidatos por Jaccard para cada comunidade A com alguma entidade compartilhada em B; não são associação um a um nem equivalência temática. Comunidades sem interseção não aparecem nessa tabela. IDs iguais não estabelecem correspondência entre fontes ou partições.

Modularidade ou concordância elevadas não garantem validade semântica. Conectividade interna é verificada e grupos desconectados são sinalizados, sem divisão ou correção automática. Notícias e visualizações de subgrafos devem fundamentar a interpretação temática posterior.
