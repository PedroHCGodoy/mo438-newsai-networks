# Caracterização e visualização das comunidades

Esta etapa utiliza partições já detectadas e verificadas. Não realiza nova detecção, extração de entidades ou relações, resolução de entidades ou cálculo de centralidades. O Neo4j/GDS continua sendo a origem das partições; os produtos visuais são construídos a partir das tabelas persistidas.

A representação principal é a projeção **não dirigida e ponderada**, coerente com a detecção de comunidades. A inspeção de relações dirigidas é uma opção complementar no mesmo HTML, identificada explicitamente. Os dados originais permanecem disponíveis nas duas representações.

## Suporte das notícias

Uma notícia pode apoiar relações em várias comunidades. Por isso, contagens por comunidade não devem ser somadas para obter o total do corpus. A identificação usa `news_id` e a versão de texto correspondente, e não o título ou o nome de uma entidade.

São preservados três escopos:

- **Interno:** a notícia sustenta pelo menos uma relação cujos dois extremos estão na mesma comunidade.
- **Fronteira:** sustenta pelo menos uma relação entre essa comunidade e outra.
- **Qualquer relação incidente:** união dos dois conjuntos anteriores.

Uma notícia pode ter evidências internas e de fronteira simultaneamente. Não se somam essas contagens para inferir o total distinto. A tabela `comunidades_noticias.csv.gz` mantém os dois indicadores por notícia e comunidade, além de título, link, fonte, data, autor, categoria editorial e estados de processamento disponíveis na rede.

As distribuições por fonte, ano e categoria contam notícias distintas em cada escopo. Cada dimensão deve recompor seu denominador de notícias. Fonte, ano e categoria vêm dos metadados da notícia. Categorias agrupadas são editoriais; não constituem classificação temática das comunidades. Autores são preservados como metadados, sem desambiguação ou agrupamento adicional nesta etapa.

O suporte inclui apenas relações usadas na rede: não equivale à quantidade de notícias selecionadas no corpus, às notícias com NER ou a uma cobertura completa e uniforme de RE. Comparações editoriais devem considerar essas diferenças de disponibilidade.

## Painel e vistas

`indice_comunidades.html` permite consultar todas as comunidades de Louvain e do Leiden definido como referência. A tabela informa tamanho, notícias internas, conectividade e até três destaques pelo PageRank global. Os IDs são os da partição verificada. Comunidades desconectadas permanecem sinalizadas; nenhuma partição é dividida ou alterada.

O painel mostra exemplos e a lista completa de notícias de suporte da comunidade, com busca e exportação CSV. Ao escolher suporte interno, a consulta restringe-se às notícias que sustentam relações internas; o outro modo inclui qualquer relação incidente.

São geradas, por padrão, duas vistas globais e vistas das três maiores comunidades de cada partição. A ausência de uma vista individual para outras comunidades é um limite explícito de geração, não ausência de sua tabela ou notícias. O parâmetro `comunidades_por_particao` controla esse limite.

Cada grafo exibe até 100 nós, ordenados pela força calculada dentro do recorte, e até 250 pares não dirigidos, ordenados pela soma dos pesos das duas direções e de todos os rótulos. Empates são resolvidos por IDs. As métricas completas e as partições não são recalculadas sobre esse recorte. Um nó pode ficar sem arestas visíveis porque suas conexões não foram selecionadas para o desenho; isso não significa isolamento na rede original.

Na vista principal, cada par de entidades tem uma conexão não dirigida. Seu peso coincide com o peso do mesmo par na projeção de comunidades: soma dos registros de todos os rótulos nas duas direções. Notícias distintas são contadas pela união dos IDs, sem somar contagens por direção. Não são criadas relações inversas ou novos fatos.

A opção **“Inspecionar relações semânticas — dirigida”** recupera todas as direções originais dos mesmos pares selecionados. Assim, um par pode aparecer com duas setas, com pesos e notícias próprios. As duas representações conservam o mesmo conjunto de pares não ordenados e a mesma soma de pesos; a inspeção pode ter até duas conexões por par. Não se aplica outro corte que descarte uma das direções durante essa alternância.

`pares_exibidos.csv.gz` identifica cada linha pela vista e pela coluna `representation`, com valores `community` ou `semantic`. Ela registra rótulos e IDs de arestas originais. As duas representações não devem ser somadas entre si, pois são descrições alternativas dos mesmos registros relacionais.

## Interação e evidências

Ao selecionar um nó, a interface oferece notícias que sustentam suas relações na rede completa, inclusive fora da vista ou comunidade atual. Ao selecionar uma conexão não dirigida, oferece a união das notícias das duas direções. Na inspeção dirigida, a consulta corresponde somente à direção selecionada. Cada consulta contém três exemplos, a lista completa filtrável e exportação CSV da seleção completa. A busca textual da lista não modifica a exportação: ela exporta todas as notícias da seleção ativa.

Os links abrem em outra aba. O HTML contém metadados, sem textos integrais das matérias. Ler a página original pode depender da disponibilidade do veículo. São aceitos links HTTP/HTTPS; títulos e nomes são tratados como texto na interface.

Os recursos de visualização são incorporados ao HTML. Não é necessário servidor HTTP para abrir os arquivos gerados, nem conexão de rede para desenhar os grafos e consultar os metadados embutidos. A abertura dos links das notícias utiliza a conexão do navegador.

## Cores, layout e interpretação

As vistas globais abrem coloridas por comunidade. Nos subgrafos de uma única comunidade, a cor inicial identifica o tipo de entidade: pessoa `#4C78A8`, organização `#F58518` e local `#54A24B`. A interface permite alternar a cor independentemente da representação das conexões. Uma comunidade mantém sua cor entre as vistas da mesma partição. As cores e IDs não estabelecem correspondência entre partições Louvain e Leiden; essa correspondência exige análise de seus membros.

O tamanho dos nós usa transformação logarítmica da força no recorte. As larguras das conexões usam transformação logarítmica do peso. Os atributos numéricos originais são preservados. A força visual não corresponde à quantidade de notícias distintas.

O layout inicial utiliza molas, semente 42 e 200 iterações, com `log1p` dos pesos apenas para posicionamento. A maior componente da vista é posicionada ao centro; as demais ficam ao redor, evitando que pequenos grupos comprimam a parte principal. As posições não representam geografia, distância geodésica exata ou teste de similaridade temática. Alterar o layout não altera nós, arestas ou comunidades.

As coordenadas iniciais são salvas em `nos_exibidos.csv.gz`. Os HTMLs iniciam sem setas e com física desativada. Permitem ativar o ajuste interativo, arrastar, ampliar, alternar para inspeção semântica e exportar PNG ou SVG. O SVG exportado preserva a opção de direção ativa, posições, nós e rótulos visíveis, com geometria simplificada das arestas. A movimentação manual no HTML não é gravada automaticamente nos arquivos do pipeline.

As figuras estáticas principais são não dirigidas e geradas em SVG, PNG e PDF a partir das mesmas posições iniciais. Rótulos são limitados aos nós de maior força; linhas finas que ligam nomes a nós são chamadas de identificação, não arestas da rede. O catálogo registra critérios e quantidade de elementos exibidos. Os desenhos são instrumentos de inspeção; não substituem a caracterização sobre a rede completa.

## Arquivos e ajustes

Resultados completos em `resultados/visualizacoes/<assinatura>/`:

- `indice_comunidades.html`: painel com todas as comunidades das partições de referência.
- `grafo_*.html`: vistas interativas selecionadas.
- `grafo_*.svg`, `.png`, `.pdf`: vistas estáticas.
- `fontes_comunidades_*.svg`, `.png`, `.pdf`: notícias de suporte interno por fonte nas dez maiores comunidades.
- `comunidades_noticias.csv.gz`: vínculo completo entre comunidades e notícias de suporte.
- `caracterizacao_comunidades.csv.gz`: métricas e quantidades de notícias por escopo.
- `distribuicoes_editoriais.csv.gz`: quantidades distintas por fonte, ano e categoria, com escopo explícito.
- `nos_exibidos.csv.gz`, `pares_exibidos.csv.gz`: dados do recorte visual, posições, IDs e rótulos originais.
- Catálogo, ambiente, leitura metodológica e manifesto com hashes.

Para modificar limites de seleção, pode-se executar novamente somente esta etapa. Isso refaz caracterização editorial e visualizações a partir dos arquivos, sem executar as etapas científicas anteriores.

`reexportar_figuras` oferece um caminho mais restrito para ajustes de fonte, tamanho e quantidade de rótulos das figuras estáticas. Lê os recortes e posições salvos, conserva as tabelas e os HTMLs e publica uma saída completa atualizada, sem recalcular métricas ou escolher outra amostra.

## Manter somente a saída atual

As funções oferecem `manter_apenas_atual`. Quando True, a saída nova é gerada e validada primeiro, e seu ZIP passa por conferência de integridade. Em seguida, o apontador é atualizado e são removidas saídas anteriores reconhecidas desta etapa dentro de `resultados/visualizacoes`: pastas de versões, ZIPs de resumo e antigas edições de figuras. A mesma política está disponível na reexportação estática.

A limpeza exige manifestos conhecidos e não remove diretórios com arquivos adicionais ou alterados. Arquivos desconhecidos, links simbólicos e outros resultados são preservados e informados para revisão. Nenhum arquivo de dados, extração, resolução, construção da rede, centralidades ou comunidades é removido. Se a geração nova falhar, a limpeza não começa. Um erro de permissão durante a limpeza é registrado em `limpeza_atual.json`.

Quando False, versões anteriores são preservadas. Esse parâmetro controla armazenamento, não a definição científica da análise. `executar=False` nunca gera ou exclui arquivos.

A alteração de dados, critérios científicos, pesos ou partições exige atualização das etapas correspondentes. A alteração de apresentação deve partir das tabelas salvas, preservando a proveniência. As figuras de etapas anteriores também podem ser regeneradas a partir de suas tabelas, mas esta função específica atende apenas à presente etapa.

## Referências técnicas

- PyVis: https://pyvis.readthedocs.io/
- vis-network: https://visjs.github.io/vis-network/docs/network/
- NetworkX, layout por molas: https://networkx.org/documentation/stable/reference/generated/networkx.drawing.layout.spring_layout.html
