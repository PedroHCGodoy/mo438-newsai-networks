# Construção das redes e proveniência das evidências

## Representação

A rede é dirigida, ponderada e multirrelacional. Um nó representa um grupo de entidades resolvidas. Uma aresta reúne registros com o mesmo ID de origem, ID de destino e rótulo de relação. Rótulos diferentes entre o mesmo par permanecem em arestas distintas. O identificador da aresta é determinístico e não depende de nomes de exibição ou da ordem das linhas.

Esta representação não é uma projeção simples. Grau, densidade, caminhos e comunidades serão definidos sobre projeções explícitas em etapas posteriores. Não interpretar automaticamente o número de arestas multirrelacionais como número de pares distintos. Nenhuma expansão por simetria, inversão ou transitividade é aplicada nesta etapa.

## Filtros

As relações `ident`, os autolaços após resolução e os registros com qualquer extremo nos grupos das fontes do corpus são preservados em auditoria e excluídos da rede. Os grupos das fontes são localizados no catálogo pelo tipo ORGANIZACAO e pelos nomes canônicos exatos: CNN Brasil, Folha de S.Paulo, Folha de S. Paulo e G1. A exclusão é aplicada por ID. Nomes semelhantes não são excluídos automaticamente; o cadastro precisa ser revisto quando houver nova resolução. Não se exclui CNN internacional, Grupo Globo ou subsidiárias apenas por semelhança textual.

Os indicadores `excluded_identity`, `excluded_self_loop` e `excluded_corpus_source` registram condições possivelmente sobrepostas. O motivo exclusivo segue a ordem identidade → autolaço → fonte, apenas para reconciliar contagens sem duplicação. As categorias de exclusão não são somadas a partir de indicadores sobrepostos.

Sinalizações técnicas e semânticas não provocam exclusões adicionais automáticas. As evidências aceitas de respostas parciais mantêm seus indicadores. Uma sinalização não comprova erro, e aprovação técnica não confirma validade semântica.

## Pesos e suporte documental

- `weight`: quantidade de registros de relação utilizados na aresta. Menções diferentes no mesmo texto podem contribuir com múltiplos registros. Não é uma medida direta de intensidade social, confiabilidade ou causalidade.
- `distinct_news_count`: número de IDs de notícias distintos que sustentam a aresta. Não se soma essa contagem para combinar arestas ou recortes: os conjuntos de notícias podem se sobrepor.
- `distinct_source_count`: quantidade de fontes distintas presentes no suporte documental.
- `review_records`, `provisional_records`, `semantic_flag_records`: contagens de registros que carregam cada indicador. Os conjuntos podem se sobrepor.

A soma dos pesos e a soma de `occurrence_count` na tabela aresta–notícia devem coincidir com a quantidade de registros utilizados. Uma aresta não pode ter mais notícias distintas do que registros.

## Universo dos nós e presença no corpus

Entram na rede apenas os grupos que participam de pelo menos uma relação utilizada após os filtros. Os outros grupos continuam no catálogo de entidades da etapa anterior: não são classificados como isolados nesta rede, pois a cobertura de RE é incompleta.

Nos nós:

- `mention_count` e `distinct_news_count` descrevem a presença NER no conjunto de notícias selecionado, inclusive quando a RE da notícia está pendente.
- `relation_news_count` descreve as notícias em que a entidade participa de relações efetivamente utilizadas.
- `review_mentions` e `entity_review_required` preservam a sinalização das menções no recorte.
- `first_observed_date` e `last_observed_date` nos nós usam a presença NER; nas arestas usam as notícias que sustentam a relação. São datas de observação no corpus, não datas de início/fim da existência da entidade ou relação.

A tabela de notícias conserva data normalizada original e precisão. Datas sem dia válido não contribuem para os extremos; não se inventam datas para completá-las. Consultar a precisão antes de interpretar intervalos finos.

## Arquivos

| Arquivo | Conteúdo |
|---|---|
| `nos.csv.gz` | IDs, nomes, tipos e contagens dos nós participantes |
| `arestas.csv.gz` | Extremos, rótulos, macrocategorias de relações, pesos e suporte |
| `noticias.csv.gz` | Notícias do recorte, títulos, links, autoria, datas, categorias e cobertura NER/RE |
| `nos_noticias.csv.gz` | Uma linha por nó–notícia: menções e participação nas relações utilizadas |
| `arestas_noticias.csv.gz` | Uma linha por aresta–notícia: contagem de registros e indicadores |
| `evidencias_relacoes.csv.gz` | ID de cada relação utilizada, ID da aresta, menções, documento/versão e sinalizações |
| `relacoes_excluidas.csv.gz` | Relações excluídas e seus motivos; IDs permitem retornar aos registros completos de entrada |
| `variantes_entidades.csv.gz` | Formas textuais das entidades e frequências no recorte |
| `qualidade_nos.csv.gz` | Métodos/estados e marcações de resolução dos nós, com contagens de menções e notícias |
| `distribuicoes_nos.csv.gz` | Presença por ano, fonte e macrocategoria jornalística |
| `distribuicoes_arestas.csv.gz` | Suporte por ano, fonte e macrocategoria jornalística |
| `grupos_fontes_excluidos.csv` | Cadastro dos grupos removidos por representarem fontes do corpus |
| `cobertura_por_ano_fonte.csv` | Quantidade de notícias por ano, fonte e estado de RE |
| `manifesto.json` | Versões, recorte, hashes, critérios e resumo de validação |

Em `distribuicoes_nos`, `count` conta menções; em `distribuicoes_arestas`, conta registros de relações. `dimension` identifica ano, fonte ou macrocategoria jornalística; `value` conserva seu valor. Valores ausentes não são removidos da distribuição. Estas tabelas permitem resumir cada dimensão, mas não substituem a tabela notícia–elemento para filtros combinados ou contagens distintas.

## Macrocategorias

`category_grouped` é a macrocategoria da notícia, obtida do mapeamento das categorias editoriais do corpus. Não é uma classificação temática nova produzida por modelo e não é categoria intrínseca da entidade. Cada nó/aresta pode aparecer em múltiplas categorias. A categoria original e o estado do mapeamento permanecem disponíveis; não é atribuída uma categoria dominante nesta etapa.

`relation_macro` descreve outro conceito: o agrupamento dos rótulos de relações. O mapeamento segue as definições adotadas na extração: inclui/incluido → inclusao; sede_de/ocorre_em → localizacao; demais relações semânticas permitidas → outra. Identidade é auditada e excluída.

## Consultas e visualizações

`consultar_noticias(projeto, entity_id=...)` retorna todas as notícias de presença NER do nó dentro do recorte. Use `somente_relacoes=True` para restringir à participação nas relações utilizadas. `consultar_noticias(projeto, edge_id=...)` retorna o suporte documental completo da aresta. O retorno inclui títulos e links, sem acessar os sites.

A seleção de exemplos e o acesso à lista completa nas visualizações HTML usarão essas tabelas. Esses controles interativos, cores, comunidades e exportação GraphML serão implementados nas etapas correspondentes. Nenhuma visualização é gerada por este módulo. Para comunidades, deduplicar os IDs de notícias das entidades e/ou arestas escolhidas, explicitando o critério.

## Recortes, atualização e limitações

`construir_rede(projeto, anos=None, fontes=None)` usa o recorte completo por padrão. Coleções de anos e fontes selecionam notícias antes da agregação e recalculam contagens; os IDs das arestas permanecem estáveis para as mesmas extremidades e rótulo. Não usar atributos da rede global diretamente como atributos de um recorte.

As saídas são versões imutáveis em `dados/processados/redes/instancias/<assinatura>/`. `atual.json` seleciona a última rede construída. Mudar recorte seleciona outra instância. O carregamento verifica integridade e compatibilidade com as entradas ativas; novas relações ou entidades exigem reconstrução.

Após ampliar a extração, executar pós-processamento, consolidação RE, integração das entidades e construção da rede, nesta ordem. Nunca somar exportações de lotes ou arestas de edições que compartilham evidências. A tabela de notícias inclui estados pendentes e permite documentar a cobertura; ausência de aresta não é evidência de inexistência de relação no texto.

Dependências: Python 3.9+ e pandas, além dos módulos locais das etapas anteriores. Nenhum acesso ao Neo4j, chave ou chamada à API é necessário.
