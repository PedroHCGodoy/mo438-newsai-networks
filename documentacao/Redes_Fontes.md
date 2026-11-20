# Redes por fonte

## Construção

O módulo `redes_fontes` carrega a rede ativa validada, confere sua assinatura e seleciona documentos pelo veículo e por um intervalo inclusivo de datas. As datas do intervalo devem possuir precisão diária ou de data/hora; datas ausentes ou imprecisas no período candidato impedem a execução. A seleção de nós decorre dos extremos das relações retidas em cada fonte. Não são acrescentados nós isolados provenientes de outros veículos ou da rede global.

Para uma aresta dirigida tipada, o peso no veículo é a soma de `occurrence_count` dos vínculos aresta–notícia selecionados. O peso global não é reutilizado. Os identificadores dos grupos e das arestas permanecem os mesmos, permitindo comparar entidades entre redes sem utilizar nomes como chaves.

O procedimento mantém as exclusões da edição global: relações de identidade, nós que representam as fontes do corpus e autolaços. Não faz novas extrações, inferências ou expansões de relações. Relações já retidas de documentos parcialmente processados não são descartadas silenciosamente. A distribuição de estados da cobertura deve acompanhar a análise.

## Atributos e evidências

Nas arestas são recalculados peso, quantidade de notícias distintas, datas observadas e sinalizadores de revisão, provisoriedade e qualidade semântica. Nos nós são recalculados menções, notícias distintas, notícias de participação relacional, revisão, datas e forças de entrada, saída e total.

Menções de um nó são contadas nas notícias da fonte e período com menções disponíveis, mesmo quando a RE não está concluída. Portanto, `distinct_news_count` e `relation_news_count` medem universos diferentes. Isso segue a definição da rede global; o nó precisa participar de ao menos uma relação retida para integrar a rede.

Categorias editoriais, autoria, estados de NER/RE, títulos e links permanecem nas tabelas documentais. As tabelas `nos_noticias` e `arestas_noticias` preservam `news_id` e `news_version_id` para ligar elementos do grafo ao cadastro de notícias. Uma lista completa pode ser obtida por junção dessas chaves, sem limitar o conjunto a exemplos visuais.

## Projeções

| Representação | Unidade de aresta | Peso |
|---|---|---|
| Dirigida e tipada | Origem, destino e rótulo | Ocorrências documentais no recorte |
| Simples não dirigida | Par não ordenado | 1 |
| Ponderada não dirigida | Par não ordenado | Soma de rótulos e ambos os sentidos |

As projeções reutilizam a implementação `redes_projecoes.preparar_tabelas`, preservando as definições da rede global. Suporte documental de um par é contado por união de notícias, sem somar contagens de rótulos diferentes como se fossem notícias distintas.

`distance=1/weight` na projeção ponderada é uma transformação disponível. Ela não representa caminhos topológicos em número de arestas nem é automaticamente a escolha adequada para distâncias. A projeção simples possui peso e distância unitários.

## Verificações

Identidades e versões documentais, ausência de duplicidades, datas, fonte do suporte, pesos inteiros positivos, sinalizadores, autolaços e identidades são conferidos. A participação de cada nó por documento é confrontada com as ocorrências das arestas. A soma das forças totais precisa corresponder ao dobro da soma dos pesos. As projeções precisam preservar os pesos e o suporte documental.

O manifesto registra hashes das cinco entradas científicas, do módulo e do módulo de projeção, período e definição dos nós. O arquivo `atual.json` aponta para a saída ativa desta etapa, sem alterar o apontador da rede global. A execução usa arquivos persistidos e não depende das variáveis de seções anteriores no kernel.

## Comparabilidade e atualização

O período comum reduz diferenças de duração, mas não elimina diferenças de seleção do corpus, quantidade e tamanho de notícias ou cobertura da RE. Densidade, concentração de graus, comunidades e centralidades devem ser interpretadas à luz dessas diferenças. Contagens divididas pelo volume de notícias não equivalem a controle experimental.

Uma ampliação das relações exige consolidar e validar uma nova edição da rede e repetir os estágios dependentes. A assinatura esperada impede incorporar uma nova edição acidentalmente. A construção destas redes não consulta outras pastas de extração.
