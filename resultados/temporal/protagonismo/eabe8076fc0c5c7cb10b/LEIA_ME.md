# Protagonismo e persistência temporal

Os graus já calculados são conferidos com os pares persistidos, sem nova
execução GDS. Força soma ocorrências incidentes; grau conta vizinhos
distintos. O grau normalizado é k/(N-1); a participação no grau é k/soma(k).
Grau crescente não implica participação relativa crescente.

Rankings usam competição com empates preservados. O Top K exato desempata
por menor ID apenas para seleção operacional. Também se exporta seleção
que inclui todos os empatados no limite, com retenção e Jaccard próprios.
Frequência entre cortes acumulados não equivale a frequência nas notícias.
As proporções sobre os 32 cortes e desde a entrada são informadas separadas.

Cada novo vizinho é confrontado com os pares novos da etapa de conexões.
O estoque de 1994 é identificado e não representa ganho desde um ano
observado anterior. Reforço não acrescenta vizinhos. O grau anterior e
os ganhos ficam salvos para futura análise de vantagem cumulativa, que
não é testada aqui. Não se conclui Efeito Mateus apenas por uma trajetória.

Notícias com menção incluem documentos com NER mesmo sem RE concluída;
notícias com participação relacional exigem relação retida. As medidas
anuais contextualizam a persistência topológica imposta pela acumulação.
Ausência prévia na rede não é preenchida com uma posição de ranking zero.

A seleção das entidades mais conectadas por tipo em 2025 é retrospectiva,
privilegiando destaques finais. Os casos configurados por ID são mantidos
separados, com seus tipos canônicos originais e documentos para inspeção.
Uma eventual interpretação metonímica ou inconsistência de tipagem não
é resolvida automaticamente. Não há fusões ou correções silenciosas.

Use entity_group_id e cutoff_year para trajetórias. Os arquivos de notícias
permitem recuperar títulos, links, categorias e exposição dos casos e das
entidades selecionadas. A soma das notícias por entidade pode contar o
mesmo documento várias vezes; para corpus, conte news_id distintos.

Não há consultas Neo4j, PageRank temporal, extração remota ou alteração da
rede. Os resultados dependem das edições verificadas das etapas anteriores.
As figuras podem ser refeitas a partir das tabelas persistidas usando
gerar_figuras em outra pasta, preservando os artefatos já verificados.
