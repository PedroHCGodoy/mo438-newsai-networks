# Evolução estrutural anual

São analisados os 32 cortes acumulados, de 1994 a 2025. Os 19 marcos de
referência são uma seleção da mesma série. Cada corte usa uma projeção
simples não dirigida, com peso unitário por par. O GDS calcula grau,
triângulos incidentes e componentes. Os resultados de todos os nós são
comparados com uma implementação independente baseada em adjacências.

A densidade é 2M/[N(N-1)]. A média principal de clusterização considera
grau pelo menos dois. Também se informa a média incluindo todos os nós.
A transitividade é 3T dividido pelo número de triplas conectadas. A maior
componente é escolhida pelo tamanho, com desempate pelo menor ID canônico.
Não se exige a presença de uma componente com fração arbitrária de nós.

Incrementos anuais e razões por notícia são descritivos. A divisão pelo
corpus e pelo suporte relacional usa denominadores diferentes; nenhuma
das razões elimina o viés de cobertura. O primeiro corte representa o
estoque inicial observado, não uma transição desde um ano anterior medido.
Anos sem suporte relacional aparecem como lacunas na figura de razões,
enquanto a topologia acumulada permanece representada nas demais figuras.

O número de componentes pode crescer com a incorporação de grupos separados
ou diminuir com a conexão entre grupos; a série agregada não identifica
sozinha esses mecanismos. Novas entidades não comprovam diversidade temática;
crescimento acumulado não comprova vantagem cumulativa. Não se ajusta lei
de potência nem se conclui sobre concentração apenas a partir destas figuras.

As projeções usam os nós persistidos da edição global já carregada no Neo4j.
São criadas uma por vez, com leitura sequencial, e liberadas após cada corte,
inclusive na ocorrência de falha, enquanto a conexão ao servidor permitir.
Não há escrita de nós ou relacionamentos persistentes. Os resultados por
ano ficam em disco e permitem retomada. O índice só muda após conclusão.

As figuras são geradas das tabelas persistidas e possuem catálogo com
objetivos e legendas. Ajustes gráficos podem reutilizar crescimento_anual.csv
e gerar_figuras sem executar o GDS novamente. As cores azul e laranja
preservam as séries correspondentes do padrão visual adotado.
