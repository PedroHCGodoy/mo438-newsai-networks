# Formação e reforço de conexões

## Pergunta analítica

A expansão da rede decorre de conexões entre duas entidades que entram
no período, da ligação entre uma entidade nova e outra já observada ou
de conexões entre duas entidades que já pertenciam à rede? Quanto do
peso acrescentado corresponde a pares novos e quanto reforça pares
anteriores?

## Unidade de análise

Utiliza-se o par simples não dirigido de entidades resolvidas. Múltiplos
rótulos e direções não geram pares distintos. A novidade é definida pela
presença dos extremos na rede acumulada no início do intervalo:

| Código | Definição |
|---|---|
| NEW_NEW | Duas entidades ausentes da rede anterior |
| OLD_NEW | Uma entidade presente e outra ausente da rede anterior |
| OLD_OLD | Duas entidades presentes, mas sem esse par na rede anterior |

O evento NEW_PAIR recebe uma dessas três classes. REINFORCED_PAIR
significa incremento de ocorrências num par já existente, sem aquisição
de um novo vizinho entre esses extremos. Pares anteriores sem incremento
são contabilizados no resumo, mas não geram linhas de evento.

Nova significa primeira presença como extremo de uma relação retida
na edição analisada. Não implica primeira menção na base, criação da
organização, nascimento de uma pessoa ou primeiro acontecimento histórico.
A resolução de entidades é compartilhada e retrospectiva. Nenhum grupo
é fundido nesta etapa.

## Resolução temporal

Os 32 cortes produzem 31 transições anuais, de 1994→1995 a 2024→2025.
A primeira rede é um estoque inicial, informado separadamente. Os
19 cortes de referência produzem 18 transições, recalculadas diretamente.

Não se somam classes anuais para obter classes de um intervalo maior.
Exemplo: uma entidade que entrou em 2023 é nova em 2022→2025, porém é
antiga em 2024→2025. Os totais de pares novos depois do estoque inicial
coincidem nas duas resoluções; sua distribuição entre classes pode mudar.
Reforços somados entre intervalos contam par-intervalo, não pares únicos.

## Pesos, documentos e verificações

A soma de ocorrências é decomposta em ocorrências de pares novos e
ocorrências em pares anteriores. A entrada de um novo rótulo semântico
em um par anterior é reforço estrutural, embora possa ser semanticamente
nova. A presente classificação não mede a novidade semântica dos rótulos.

Cada incremento de peso e de quantidade de notícias por par é confrontado
com a agregação independente das evidências aresta-notícia do intervalo.
Também se verificam preservação das entidades e dos pares, extremidades
estáveis, pesos não decrescentes, dimensões da caracterização estrutural
e recomposição dos totais finais a partir do estoque e dos incrementos.

As ocorrências refletem registros retidos, inclusive inversas e repetições
presentes na edição. Não são fatos independentes nem confiança semântica.

Para inspecionar os documentos, use pair_id em eventos_pares_anuais.csv.gz
ou eventos_pares_marcos_referencia.csv.gz. Filtre pares_noticias.csv.gz
por esse identificador e por previous_year < publication_year <= cutoff_year.
Associe news_id e news_version_id a noticias_suporte.csv.gz para recuperar
títulos, links, datas, autores e categorias disponíveis. Os IDs das
extremidades apontam para catalogo_entidades.csv.gz. Um documento pode
sustentar vários pares; conte IDs distintos para medir notícias.

## Figuras e interpretação

São preservadas a composição percentual por classe e as curvas de
novos pares por notícia. As cores são azul para nova–nova, laranja para
antiga–nova e verde para antiga–antiga. Também se apresenta novidade
versus reforço e a composição entre os marcos de referência. Cada figura
possui objetivo e legenda no catálogo e versões SVG, PNG e PDF.

Razões por notícia utilizam corpus ou suporte relacional como denominador;
não são médias individuais nem correção de viés. Intervalos sem pares
novos não têm composição percentual definida. Ausência de extração não
demonstra ausência de relações. A quantidade de oportunidades possíveis
difere entre as classes; uma participação maior não é, por si só, maior
propensão de conexão.

## Relação com a investigação de vantagem cumulativa

Pares antiga–nova não demonstram conexão preferencial; pares antiga–antiga
não demonstram Efeito Mateus. Na etapa posterior, o caso EUA e outros
casos serão examinados por identificadores conferidos no catálogo, com
grau anterior, aquisição de vizinhos, reforço e exposição documental.
Padrões compatíveis serão distinguidos de afirmações de causalidade.

## Execução e reprodução

A análise lê as tabelas das redes anuais e os resultados estruturais
persistidos, preservando suas assinaturas. Não acessa Neo4j nem APIs de
extração: a tarefa é uma comparação de conjuntos, como na implementação
de origem. A rede global e as extrações paralelas não são modificadas.
Uma nova edição dos insumos gera resultados em outra pasta versionada.
Repetir a execução reutiliza resultados compatíveis após conferir hashes.
Os cálculos não dependem de DataFrames de células executadas anteriormente.

Para ajustes gráficos, gerar_figuras pode ler formacao_anual.csv e
formacao_marcos_referencia.csv e salvar em outra pasta. Não é preciso
refazer a classificação ou os algoritmos estruturais.
