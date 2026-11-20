# Comunidades ponderadas por fonte

## Projeção e parâmetros

As redes por fonte e período fornecem os pares não dirigidos e seus pesos agregados. Cada par aparece uma vez na tabela em disco; o GDS utiliza representação não dirigida com dois registros de adjacência. A verificação compara todos os IDs, extremos, multiplicidades, pesos e distâncias esperados. A modularidade local usa os pesos sem esse espelhamento, como na análise global.

São reutilizadas as definições de `redes_comunidades`: Louvain ponderado, até 20 níveis e 20 iterações; Leiden ponderado, até 10 níveis, `gamma=1.0`, `theta=0.01`, sementes 42, 43 e 44. Ambos usam tolerância `1e-4` e concorrência 1. A projeção usa leitura com concorrência 1 e é liberada após as execuções da fonte, sem remover outras projeções ou dados persistentes.

Documentação das interfaces: [Louvain](https://neo4j.com/docs/graph-data-science/current/algorithms/louvain/) e [Leiden](https://neo4j.com/docs/graph-data-science/current/algorithms/leiden/).

## Partições e caracterização

Todos os nós devem receber exatamente uma comunidade por execução. Os IDs originais são preservados e os canônicos correspondem ao menor ID de entidade de cada comunidade. As partições são salvas com hashes, configuração e versão GDS para retomada. Não se misturam checkpoints de versões diferentes do GDS na mesma série.

Modularidade ponderada padrão é calculada localmente com resolução 1. São exportados pesos internos e de fronteira, condutância, densidade interna, fração de nós, composição PESSOA/ORGANIZACAO/LOCAL e quantidade de partes conexas. A partição pelas componentes originais fornece uma referência de fragmentação; não é modelo nulo amostrado nem teste de significância.

As cinco entidades de destaque de cada comunidade são ordenadas pelo PageRank já calculado na rede completa da fonte. Não se calcula PageRank novamente dentro de cada comunidade. Esse destaque estrutural não determina automaticamente o tema do grupo.

Comunidades desconectadas e comunidades que atravessem componentes originais são sinalizadas. A partição retornada é preservada integralmente: não há divisão, fusão ou correção automática para melhorar as métricas.

## Estabilidade dentro da fonte

ARI e NMI aritmética são calculados entre todas as duplas das quatro partições, na rede completa e em sua restrição à maior componente. Os algoritmos não são reexecutados somente na maior componente. Essa restrição ajuda a distinguir concordância na principal estrutura conectada da concordância associada a pequenas componentes.

Louvain é a referência principal; a primeira semente de Leiden é referência complementar predefinida. Não se escolhe a partição pelo maior valor observado de modularidade. Louvain não recebe uma semente nesta configuração; por isso, as partições persistidas são a referência da edição, e não se promete reprodução idêntica em toda reexecução ou versão do servidor.

## Comparação entre fontes

Louvain e Leiden de referência são comparados separadamente entre cada par de fontes. ARI/NMI usam somente os IDs de entidades que aparecem em ambas as redes, e a quantidade dessa interseção é explicitamente exportada. Não há imputação de comunidades para entidades ausentes.

Para comunidades com alguma entidade compartilhada, calcula-se Jaccard com os tamanhos completos das comunidades nas duas fontes. A tabela apresenta, para cada comunidade A com interseção em B, o candidato de maior Jaccard, com desempate por maior interseção e menor ID de B. A correspondência é direcional A→B, pode ser muitos-para-um e não estabelece equivalência temática. Comunidades sem interseção não aparecem nessa tabela; continuam nas tabelas completas.

Correspondências com uma ou poucas entidades devem ser avaliadas considerando os tamanhos e a interseção, sem limiares interpretados como garantias. IDs canônicos iguais em fontes ou partições distintas não estabelecem correspondência.

## Reprodução e limites

As edições global, por fonte, estrutural e de centralidades são conferidas antes do cálculo. Configurações, código científico, versão GDS, estimativas e tempos são registrados. Uma única projeção desta etapa permanece ativa por vez; os resultados completos e checkpoints são persistidos. O dimensionamento adequado do heap continua necessário.

Modularidade, ARI e NMI não são validação semântica. Cobertura incompleta de RE, composição do corpus, tamanho das redes, rótulos inversos e resolução de entidades afetam a organização observada. A interpretação temática requer inspeção de entidades, relações e notícias; as tabelas documentais permanecem nas etapas anteriores para vinculação às comunidades.
