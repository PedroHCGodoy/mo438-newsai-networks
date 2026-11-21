# Formação de conexões

São comparadas 31 transições anuais e 18 transições entre os 19 marcos
de referência. A rede de 1994 é o estoque inicial, não uma transição
desde um ano previamente observado. Ambas as resoluções utilizam todas
as relações disponíveis no respectivo intervalo e o mesmo último corte.

Um par novo conecta duas entidades antes sem conexão na projeção simples
não dirigida. As classes nova–nova, antiga–nova e antiga–antiga dependem
da presença dos extremos na rede acumulada no início do intervalo. Nova
significa primeira presença como extremo de relação retida nesta edição,
não primeira menção no corpus nem surgimento histórico da entidade.

O reforço conta novas ocorrências em pares já existentes. Rótulos ou
direções adicionais em um par anterior não são pares novos. Os pesos
agregam registros retidos e podem incluir inversas e repetições; não são
contagens de fatos independentes nem escores de confiança semântica.

Categorias dos intervalos de referência são recalculadas nas suas próprias
fronteiras; não se somam as classes anuais para obter classes de intervalos
maiores. A mesma entidade pode ser nova em um intervalo de três anos e
antiga no segundo ou terceiro ano quando a resolução é anual. Isso altera
a composição das classes, mesmo com o mesmo conjunto final de pares.

Reforços somados entre intervalos contam par-intervalo, não pares únicos.
As proporções têm denominador igual ao número de pares novos; não são
probabilidades de conexão entre todos os pares possíveis de cada classe.
A quantidade de oportunidades é diferente entre as classes. Predomínio
de antiga–nova ou reforço não demonstra conexão preferencial ou Efeito
Mateus. Essa investigação requer grau anterior, exposição e comparação.

O suporte por par/documento recompõe integralmente os incrementos de peso
e notícias de cada transição. Use pair_id para chegar a pares_noticias.csv.gz,
depois news_id e news_version_id para noticias_suporte.csv.gz, que preserva
títulos, links e categorias. source_id e target_id identificam entidades
no catálogo. Um documento pode apoiar vários pares: não some as linhas
do suporte para obter o total de notícias distintas.

Razões por notícia são descritivas e não corrigem cobertura ou seleção.
Anos sem suporte são lacunas nas curvas de razões; ausência de pares novos
pode ocorrer mesmo com extração disponível. A classificação utiliza apenas
arquivos persistidos, sem Neo4j, NER, RE ou novas resoluções de entidades.
Os resultados da rede global e das outras etapas permanecem preservados.
