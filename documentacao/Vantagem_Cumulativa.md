# Grau anterior e aquisição de novos vizinhos

Pergunta: entidades já presentes com maior grau em t−1 adquirem mais
vizinhos distintos no ano t? Unidade: entidade × transição anual. São
31 transições, de 1994→1995 até 2024→2025. O estoque de 1994 não é um
ganho observado. Entrantes são auditados, mas não entram como nós com
grau anterior zero; todos os nós anteriores permanecem, inclusive com
ganho zero e sem notícia observada no ano. O grau é o da projeção simples
não dirigida. Reforço soma ocorrências em pares que já existiam.

Referências de alocação, entre n nós anteriores com ganho total G:
uniforme U_i=G/n; proporcional D_i=G*k_i/soma(k). Ambas conservam G.
Não são modelos geradores de grafos, não impõem restrições de pares e
não são testes nulos probabilísticos. Não incorporam saturação: cada nó
tem no máximo N_t−1−k_i vizinhos novos possíveis. Comparações por faixa
fixa informam número de nós, média de ganho, chance empírica de ganho
positivo e participações. Não se ajusta regressão log-log nem expoente
de conexão preferencial. Ganho normalizado divide pela média anual
de ganho entre nós anteriores. Ano sem ganhos produz valor ausente.

Spearman usa postos médios nos empates e não fornece p-valor ou intervalo
de confiança iid. Ano sem variação produz INSUFFICIENT_VARIATION, não
evidência de ausência de associação. Cada ano é analisado separadamente;
não se agregam linhas de anos distintos para inferência independente.
Comparações por tipo e subconjuntos com ≥1 e ≥5 notícias com menção são
sensibilidades. Estratos de tipo, idade na rede (0–2, 3–9, 10+) e menções
(0, 1, 2–4, 5+) são descritivos; seus cortes não têm validade universal.
Exposição é contemporânea ao ganho e pode participar do mecanismo; não
é controle causal. Estratos pequenos ou constantes ficam identificados.
Idade é tempo desde a primeira aparição nesta rede, não idade real.

Cobertura de RE, volume de notícias, extrações parciais, tipo de entidade,
antiguidade, diferenças de exposição e resolução de entidades podem
afetar a associação. A normalização anual não corrige seleção de notícias
nem lacunas de extração. Em 2021, sem RE concluída nesta edição, ausência
de ganho não representa ausência de novas relações no noticiário.

O caso utiliza todos os anos elegíveis. Comparadores no mesmo estrato
incluem o próprio caso e não formam grupo de controle independente.
Estados Unidos e EUA não são fundidos nem reclassificados. Os títulos,
links e atributos das notícias são preservados no arquivo dos casos;
uma menção não garante participação em relação retida.

Uma associação positiva é compatível com vantagem cumulativa observada,
mas não identifica causalidade, não comprova conexão preferencial linear
nem Efeito Mateus sociológico. Concentração, cauda dos graus, persistência
e associação temporal respondem a perguntas diferentes.

Referência: Jeong, Néda e Barabási (2003), Measuring preferential attachment
in evolving networks, EPL 61, 567–572. DOI: 10.1209/epl/i2003-00166-9.
A análise utiliza cortes anuais agregados; não reproduz a sequência
intra-anuais de ligação usada em modelos de crescimento.
