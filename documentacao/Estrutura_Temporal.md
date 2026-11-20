# Evolução estrutural das redes acumuladas

## Perguntas e representação

Como a conectividade, a fragmentação e o fechamento de vizinhanças mudam
ao incorporar notícias? O tamanho da maior componente cresce junto de
sua participação na rede? A entrada de novos nós acompanha a entrada de
novos pares conectados? A série anual de 1994 a 2025 permite investigar
essas perguntas e manter a seleção dos 19 marcos de referência.

O objeto estrutural é a projeção simples não dirigida e não ponderada:
uma aresta por par, independentemente de rótulos e direções. A rede
semântica dirigida e ponderada permanece preservada nos arquivos de
construção; não é substituída pela projeção estrutural.

## Cálculos e verificações

GDS executa degree, triangleCount e wcc. O grau conta vizinhos distintos;
o número de arestas simples é metade da soma dos graus. A densidade é
2M/[N(N-1)]. Cada nó participa de k(k-1)/2 triplas centradas nele.

A clusterização local divide os triângulos incidentes pelas triplas do
nó. A média principal usa grau pelo menos dois, e a média sobre todos os
nós também é exportada, atribuindo zero aos de grau menor que dois.
A transitividade divide três vezes os triângulos distintos pelo total
de triplas conectadas. As duas medidas possuem ponderações diferentes.

Componentes, graus e triângulos de todos os nós são conferidos contra
uma implementação independente. Os IDs arbitrários das componentes são
canonizados pelo menor ID de entidade. A maior componente é a de maior
tamanho, com desempate pelo menor ID. Nenhum limiar é usado para garantir
que a rede possua uma componente gigante.

## Crescimento e figuras

A tabela anual informa incrementos de nós, pares simples, arestas tipadas
e ocorrências. O primeiro corte é o estoque inicial observado. As razões
de incremento por notícia usam dois denominadores: corpus anual e suporte
relacional anual. São razões de totais, não médias de novidade por notícia.
Nenhuma controla integralmente o viés de seleção ou a composição dos textos.

Anos sem suporte são identificados. Na figura de razões, aparecem como
lacunas; nas figuras de topologia acumulada, a rede continua representada.
Todas as figuras possuem objetivo e legenda em catalogo_figuras.csv e são
exportadas em SVG, PNG e PDF. Azul e laranja identificam as séries de
novas entidades e novos pares, respectivamente.

Novas entidades podem formar componentes separadas; novas conexões podem
unir componentes. Contudo, mudanças agregadas no número de componentes
não identificam sozinhas a contribuição de cada mecanismo. Densidade
decrescente pode coexistir com mais conexões e grau médio crescente.
Não se infere significado editorial ou causal apenas dessas métricas.

## Protagonismo e vantagem cumulativa

Uma análise posterior investigará EUA e outras entidades relevantes,
usando os mesmos IDs resolvidos em todos os cortes. O caso EUA deverá ser
localizado e conferido no catálogo canônico; nomes parecidos não serão
fundidos automaticamente. A seleção de outros casos deverá ser explícita,
incluindo diferentes tipos e, quando viável, graus iniciais comparáveis.

Será distinguido crescimento acumulado de aquisição posterior de novos
vizinhos. Investigar-se-á a associação entre grau anterior e novos vínculos,
considerando exposição documental, cobertura de RE e tempo de observação.
Reforço de vínculos existentes e ganho de novos vizinhos são fenômenos
distintos. Frequência nas notícias e grau também não são equivalentes.

Esses dados podem mostrar padrões compatíveis com vantagem cumulativa,
mas não demonstram por si só um mecanismo causal ou Efeito Mateus. Uma
cauda pesada ou eventual ajuste de lei de potência tampouco prova esse
mecanismo. A investigação da cauda de graus, com comparação de modelos,
e o Gini complementar serão tratados separadamente. Os graus por nó e
ano ficam persistidos nesta etapa para permitir essas análises.

## Execução e retomada

A análise utiliza os nós globais já persistidos no Neo4j. Uma projeção
GDS é criada por corte, com leitura sequencial, e liberada antes do
próximo. As consultas não criam nós nem relacionamentos persistentes.
Os algoritmos utilizam quatro trabalhadores, conforme a análise global.

Resultados e verificações são salvos por ano. A repetição confere os
arquivos existentes e reutiliza cortes compatíveis. Arquivos alterados
interrompem a execução. Bloqueios após interrupção abrupta só devem ser
arquivados depois de confirmar que a execução anterior terminou.

Os resultados se vinculam à assinatura da série temporal e à edição
global. Novas extrações devem gerar outra edição e os resultados
dependentes correspondentes. Não há incorporação automática de extrações
em andamento. Ajustes nas figuras podem ler crescimento_anual.csv e
chamar gerar_figuras em outra pasta, sem repetir os algoritmos GDS.
