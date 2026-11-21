# Cauda e concentração dos graus

O estimador principal é o modelo discreto de lei de potência por máxima
verossimilhança, sem a aproximação estimate_discrete. O limiar xmin é
selecionado pela distância KS. A fração
da rede efetivamente ajustada e os sinais numéricos são registrados.
Caudas com menos de 50 nós são sinalizadas operacionalmente; 50 não é
um limiar de validade científica. Nenhum ajuste usa regressão em log-log.

Lognormal, exponencial e lei de potência com corte exponencial são
comparadas na mesma amostra acima do xmin da lei de potência. As outras
distribuições seguem as implementações e discretizações de powerlaw 1.5;
estimate_discrete=False não torna exatas todas as distribuições alternativas.
A razão de log-verossimilhança é não normalizada: positiva favorece a
lei de potência; negativa favorece a alternativa. Para o corte exponencial,
o teste é aninhado e sua calibração requer cautela, inclusive na fronteira
do parâmetro de corte. Avisos e flags numéricos impedem leitura automática
de preferência confiável. Não se escolhe vencedor apenas pelo sinal de R.

O bootstrap de 2025 mistura o corpo empírico com a cauda de lei de potência
e refaz a seleção de xmin e o ajuste em cada réplica. Os resultados ficam
salvos para retomada, com semente por réplica e restauração do estado
aleatório externo. O p-valor usa correção de uma unidade; sua precisão
Monte Carlo é informada. Falhas não são descartadas silenciosamente:
se qualquer réplica falhar, o resumo fica incompleto e não informa p.

Trata-se de referência univariada iid, não de simulação de redes. Graus
de uma rede não são observações independentes; a simulação não preserva
dependência ou restrição k≤N−1 e pode gerar valores maiores. Os p-valores
do bootstrap e das razões, assim como sigma, são diagnósticos sob essa
aproximação. Não fornecem garantia inferencial para a rede observada.
Não rejeitar o modelo não prova que ele seja verdadeiro; preferi-lo a uma
alternativa não comprova adequação absoluta. Uma cauda ajustada não basta
para chamar toda a rede de livre de escala ou demonstrar Efeito Mateus.

Gini e participações superiores são complementares, sobre todos os nós.
Essas medidas descrevem concentração; a lei de potência trata da forma
da distribuição na cauda. Elas não respondem à mesma pergunta e não
substituem o teste posterior de associação entre grau anterior e ganhos.

Referências metodológicas: Clauset, Shalizi e Newman (2009), DOI
10.1137/070710111; Alstott, Bullmore e Plenz (2014), DOI
10.1371/journal.pone.0085777. A análise utiliza apenas graus persistidos,
sem extração remota ou consulta ao Neo4j.
