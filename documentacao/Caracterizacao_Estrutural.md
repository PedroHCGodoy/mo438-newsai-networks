# Caracterização estrutural básica

## Escopo

A rede analisada é a projeção simples, não dirigida e não ponderada, composta pelos nós participantes das relações utilizadas e pelos pares não ordenados distintos. Não se usam arestas tipadas paralelas no cálculo de grau ou densidade. Peso unitário representa adjacência; pesos de frequência e atributos semânticos permanecem nas outras representações.

## Métricas e convenções

Para N nós, M arestas simples e grau k_i:

- Grau médio: 2M/N; validação independente pela soma dos graus, que deve ser 2M.
- Densidade: 2M/[N(N−1)] para N>1; zero para N=1.
- Triângulos incidentes T_i: número de triângulos que contêm i. O total de triângulos é ΣT_i/3.
- Triplas conectadas centradas em i: k_i(k_i−1)/2. Cada tripla possui um centro; um triângulo contém três triplas fechadas.
- Clusterização local: C_i = T_i / [k_i(k_i−1)/2] para k_i≥2. Para graus menores, adota-se C_i=0.
- Média principal: média de C_i somente sobre k_i≥2. A média sobre todos os nós é registrada como outra convenção, sem trocar os nomes.
- Transitividade: ΣT_i / Σ[k_i(k_i−1)/2]. Não é, em geral, igual à média não ponderada dos coeficientes locais.

Se não houver nós elegíveis ou triplas, a respectiva média/transitividade é indefinida e registrada como null, não como zero. O coeficiente local de nós de grau menor que dois permanece zero pela convenção declarada.

A distribuição dos graus registra contagem, probabilidade e CCDF P(K≥k) nos graus observados. Não é realizado ajuste de lei de potência, inferência de rede livre de escala ou teste de vantagem cumulativa nesta etapa. Essas investigações requerem procedimentos próprios.

## Componentes

O GDS WCC é executado sobre a projeção não dirigida. Identifica componentes conexas, não partições comunitárias. Os IDs de retorno são arbitrários e são convertidos em IDs canônicos pelo menor ID de entidade de cada componente. Essa canonização permite comparar partições sem depender da numeração interna do algoritmo.

O ranking ordena componentes por tamanho decrescente e ID crescente. Em caso de empate, uma maior componente é selecionada por esse critério explícito. O tamanho e a proporção da maior componente são descritivos; a análise das distâncias e do diâmetro será restrita e documentada em etapa própria.

## Algoritmos e eficiência

O GDS executa uma única chamada de stream para grau, uma para triângulos e uma para componentes, com concurrency=4. Estimativas de memória são consultadas antes das execuções e registradas junto aos tempos. Não se grava ou modifica propriedades dos nós/projeções.

O coeficiente local é obtido da contagem de triângulos e do grau, pela fórmula exata. Isso evita recalcular graus para cada nó e repetir contagens de triângulos em chamadas independentes de clusterização.

Uma implementação local constrói adjacências da tabela simples. Conta triângulos por orientação dos pares segundo (grau, ID), enumerando cada triângulo uma única vez. Componentes são obtidas por busca em profundidade. Todos os graus, triângulos e IDs canônicos de componente devem coincidir com os retornos GDS. Essa é uma verificação técnica de cálculo/topologia, não uma avaliação semântica das extrações.

## Arquivos

- `metricas_nos.csv.gz`: ID, grau, triângulos, triplas, componente, clusterização local, nome e categoria de entidade.
- `resumo_metricas.csv`: métricas globais e indicadores de validação.
- `distribuicao_graus.csv`: distribuição empírica e CCDF.
- `componentes.csv`: tamanho, ranking e proporção de nós por componente.
- `distribuicao_tamanhos_componentes.csv`: frequência de cada tamanho observado.
- `distribuicao_clusterizacao.csv`: histograma local com intervalos declarados.
- `execucao_gds.json`: estimativas e tempos por algoritmo.
- `catalogo_figuras.csv`: arquivos, objetivos analíticos e legendas.
- `interpretacao_inicial.md`: descrição factual inicial, a ser integrada à discussão científica.
- `manifesto.json`: entradas versionadas, convenções, código, resumo e hashes das saídas.

As figuras são exportadas em SVG, PNG e PDF. A figura CCDF usa pontos em escala log-log; graus zero não aparecem nesse eixo. O histograma de clusterização inclui nós de grau menor que dois em zero. O gráfico de tamanhos de componentes usa eixo categórico para tamanhos e frequência logarítmica; as distâncias entre barras não representam diferenças numéricas entre tamanhos.

## Atualização e limites

As saídas são imutáveis por assinatura de rede, projeção e código. A reutilização exige integridade dos arquivos. Uma mudança de dados exige reconstruir as etapas dependentes. As estatísticas descrevem a rede observada sob cobertura e filtros declarados; ausência de aresta não comprova ausência de relação no corpus ainda não processado.

A etapa não calcula distância média, diâmetro, comunidades ou centralidades adicionais. Também não estabelece validade científica de agrupamentos ou extrações apenas por passar em testes de consistência.

## Referências técnicas

- Grau GDS: https://neo4j.com/docs/graph-data-science/current/algorithms/degree-centrality/
- Triângulos GDS: https://neo4j.com/docs/graph-data-science/current/algorithms/triangle-count/
- Componentes GDS: https://neo4j.com/docs/graph-data-science/current/algorithms/wcc/
