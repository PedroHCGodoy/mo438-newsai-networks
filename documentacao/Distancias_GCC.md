# Distâncias geodésicas na maior componente

A análise utiliza a projeção simples, não dirigida e não ponderada. A maior componente conexa é selecionada pelas tabelas estruturais verificadas. Em empate de tamanho, utiliza-se o menor identificador canônico. Identificadores de entidades são preservados nas saídas, permitindo cruzamentos com os nós e suas notícias de suporte.

## Definições

A distância d(u,v) é o menor número de arestas entre dois vértices. A distância média da componente é a soma das distâncias sobre os N(N−1) pares ordenados de vértices distintos, dividida por N(N−1). Em uma rede não dirigida, contar cada par duas vezes não altera a média.

A excentricidade e(u) é a maior distância entre u e outro vértice da componente. O diâmetro é o máximo das excentricidades e o raio é o mínimo. Um vértice mais distante é registrado por fonte; empates são resolvidos pelo menor ID na ordenação dos vértices. A tabela não enumera todos os pares empatados.

Estas métricas descrevem a maior componente. Não representam distâncias finitas entre vértices de componentes diferentes. Um comprimento geodésico pequeno não demonstra influência, causalidade ou qualidade da informação extraída. A interpretação depende da cobertura do corpus e das extrações.

## Implementação

São utilizados Dijkstra no modo `unweighted=True` da SciPy e uma matriz de adjacência esparsa CSR, simétrica e com valores unitários. A opção faz a distância corresponder ao número de arestas. Pesos de frequência e distâncias inversas das relações não entram neste cálculo.

Todas as fontes são percorridas, em ordem crescente de `entity_group_id`. A execução em blocos limita a matriz temporária a B×N distâncias, em vez de armazenar N×N. São persistidos apenas totais por fonte, excentricidades e histogramas por bloco. O custo computacional continua dependendo de todas as fontes: a organização em blocos reduz memória e permite retomada, sem tornar o algoritmo subquadrático.

Blocos concluídos são salvos atomicamente com sincronização em disco e hash do conteúdo. A retomada verifica a assinatura das entradas, a ordem e a integridade dos blocos. Uma interrupção pode exigir repetir o bloco ainda não concluído. Não inicie duas execuções simultâneas no mesmo projeto.

Um resultado completo da mesma versão é conferido e reutilizado. Alterações de rede, projeção, caracterização estrutural, código ou versão da SciPy geram outra versão. `max_fontes` e tamanho de bloco são controles de execução e podem mudar na retomada da mesma versão.

## Verificações

- Correspondência de rede, projeção e caracterização estrutural por assinaturas e arquivos verificados.
- Conferência de todos os graus e componentes a partir das arestas locais.
- Comparação integral das distâncias de até três fontes com busca em largura independente: menor ID, maior ID e um nó de grau máximo.
- Distâncias inteiras e finitas; exatamente uma distância zero por fonte, na diagonal.
- N−1 outros vértices alcançados por fonte.
- Na conclusão: N(N−1) pares, contagens pares para cada distância, 2M pares a distância um e igualdade entre a soma dos histogramas ponderados e a soma por fonte.

A conferência independente de três fontes valida esses vetores integralmente; não constitui comparação independente de todos os pares.

## Execução parcial

`max_fontes=16` calcula até 16 fontes adicionais para medir desempenho. A seleção é determinística e não é uma amostra aleatória: a média dessas fontes não é publicada como estimativa da média global. Distância média, raio e diâmetro finais ficam vazios até a conclusão de todas as fontes.

São reportados limites provisórios: o maior valor de excentricidade observado é um limite inferior do diâmetro; duas vezes a menor excentricidade observada, limitado a N−1, é um limite superior. Para o raio, os limites são o teto de metade do limite inferior do diâmetro e a menor excentricidade observada. Somente resultados completos alimentam o apontador `atual.json` para análises posteriores.

Na componente de um único vértice, raio e diâmetro são zero, e a média entre vértices distintos é indefinida (vazia).

## Arquivos

- `resultados/distancias/execucoes/<assinatura>/blocos/`: checkpoints para retomada.
- `resultados/distancias/parciais/`: relatórios de execuções incompletas, preservados separadamente.
- `resultados/distancias/instancias/<assinatura>/`: resultado completo e manifesto.
- `distancias_por_fonte.csv.gz`: ID, nome e tipo da entidade, soma das distâncias, número de destinos, média, excentricidade e ID de um vértice mais distante.
- `distribuicao_distancias.csv`: número e fração dos pares por distância. Nos relatórios parciais, contém apenas os pares percorridos.
- `resumo_metricas.csv`, `manifesto.json`, `ambiente.json` e `LEIA_ME.md`: métricas, proveniência, tempos e convenções.

A conclusão gera duas figuras em SVG, PNG e PDF: distribuição das distâncias (laranja, para a maior componente) e distribuição das excentricidades (azul). Cada figura possui objetivo analítico no catálogo.

## Dependências e reprodução

Utiliza Python, NumPy, pandas, SciPy e matplotlib, além dos módulos de carregamento das etapas anteriores. As versões são registradas em `ambiente.json`. A instalação deve ocorrer no mesmo kernel Jupyter da análise. Não há conexão com Neo4j, NER, RE ou APIs pagas nesta etapa; as tabelas verificadas bastam mesmo após reinício do servidor.

Documentação do algoritmo: https://docs.scipy.org/doc/scipy/reference/generated/scipy.sparse.csgraph.dijkstra.html
