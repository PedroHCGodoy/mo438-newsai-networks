# Protagonismo e persistência das entidades

## Perguntas

Quem aparece entre as entidades mais conectadas em cada corte? Há
renovação dos rankings? Grau, força relacional e exposição documental
contam a mesma história? Ganhar novos vizinhos é diferente de acumular
mais ocorrências nas conexões existentes?

## Medidas

São reutilizados os graus verificados dos 32 cortes. As contagens de
conectividade e força utilizam a mesma função da análise global, com
conferência dos pares simples e dos totais de pesos. Não há PageRank
temporal ou nova execução de algoritmos GDS nesta etapa.

| Campo | Significado |
|---|---|
| degree | Vizinhos distintos na projeção simples não dirigida |
| weighted_strength | Soma dos pesos incidentes de entrada e saída |
| degree_normalized | Grau dividido por N−1 |
| degree_share | Grau dividido pela soma dos graus do corte |
| distinct_news_count | Notícias do período com menção ao grupo |
| relation_news_count | Notícias com participação do grupo em relações retidas |
| annual_mention_news | Notícias do ano com menção, mesmo sem RE concluída |
| annual_relation_news | Notícias do ano com participação relacional |
| new_neighbors | Incremento do grau; em 1994 representa estoque inicial sinalizado |
| reinforcement_occurrences | Incremento de ocorrências em pares já existentes |

As formas de contagem diferem: uma notícia pode contribuir com várias
menções, relações e vizinhos. Somar notícias entre entidades pode contar
um mesmo documento várias vezes. A força depende de repetições e de
relações inversas retidas; não representa confiança ou fatos independentes.

## Rankings, empates e persistência

O ranking usa método min: graus 10, 8, 8, 3 recebem posições 1, 2, 2, 4.
O Top K exato escolhe por grau e depois menor ID. Essa ordem é operacional,
sem afirmar superioridade entre empatados. A seleção inclusiva preserva
todos os empatados na posição K. As duas seleções têm retenção e Jaccard
próprios, nas transições anuais e nos 19 marcos de referência.

Retenção divide a interseção pelo grupo anterior. Jaccard divide pela
união. As frequências são apresentadas sobre os 32 cortes e sobre os
cortes desde a entrada da entidade. A permanência topológica decorrente
da acumulação não implica presença nas notícias em cada ano; para isso,
consulte as medidas anuais de exposição e participação relacional.

## Seleção de casos e figuras

São selecionadas retrospectivamente cinco entidades por tipo no corte
de 2025, com desempate por ID, além dos casos explicitamente configurados.
Esse critério privilegia destaques finais e não constitui amostra sem viés.
As curvas por tipo usam o ranking global, não a posição dentro do tipo;
ambos os rankings são exportados na tabela completa.

Os casos Estados Unidos (5276; LOCAL) e EUA (32443; ORGANIZACAO) permanecem
separados. Exemplos documentais conferidos para o segundo grupo fazem
referência ao país ou à atuação estatal, como disputa comercial, ação
militar e diplomacia. A amostra não valida todas as menções e não decide
automaticamente entre leitura metonímica e erro de tipagem. A tipagem e
os grupos são preservados nesta edição, com limitação explícita. Novos
casos devem ser selecionados por ID após conferir o catálogo e o suporte.

Quatro figuras em SVG, PNG e PDF mostram retenção, trajetórias por tipo,
casos de conectividade/exposição e frequência entre destaques. As cores
dos tipos seguem o padrão global. Os objetivos e legendas ficam no catálogo.

## Vantagem cumulativa

Os ganhos individuais de vizinhos são conferidos contra os eventos de
pares novos da etapa anterior. São separados os ganhos para vizinhos já
observados ou novos. O grau anterior e a exposição são preservados para
uma investigação posterior de associação entre posição anterior e
aquisição de conexões. O estoque inicial de 1994 é marcado para exclusão
das análises de ganhos observados entre cortes.

Esta etapa é descritiva: não testa conexão preferencial nem Efeito Mateus.
Rankings persistentes, força crescente e associação visual não demonstram
um mecanismo de vantagem cumulativa. Na investigação posterior, cobertura,
oportunidades de conexão, frequência documental e tamanho da rede deverão
ser considerados. Os rótulos canônicos não serão corrigidos silenciosamente.

## Arquivos e reprodução

trajetorias_entidades.csv.gz contém todas as entidades presentes em cada
corte, sem imputar posição antes de sua entrada. top_exato.csv e
top_com_empates.csv preservam as duas regras de seleção. As tabelas de
persistência e frequência permitem comparar estabilidade e renovação.

entidades_noticias.csv.gz contém todos os vínculos documentais das
entidades selecionadas. casos_noticias.csv.gz restringe aos casos
configurados, com títulos, links e categorias disponíveis. A seleção
documental inclui menções sem RE concluída, identificadas pelo estado
do processamento. auditoria_casos.csv registra IDs e tipos preservados.

As entradas são verificadas por assinatura e integridade. A repetição
reutiliza resultados compatíveis. Ajustes gráficos podem chamar
gerar_figuras sobre as tabelas persistidas em uma nova pasta, sem refazer
os cálculos. A rede e as extrações paralelas permanecem preservadas.
