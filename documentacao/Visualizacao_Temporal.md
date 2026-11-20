# Exploração temporal de entidades e destaques automáticos

Os 32 cortes são acumulados desde 1994. Os destaques são totalmente
seletivos por dados: grau decrescente da rede completa do corte, com
inclusão de todos os empatados na 15ª posição. Na presente edição há
15 a 25 destaques por ano. O ranking de competição preserva empates;
o ID apenas ordena a exibição dentro de um empate. Grau é número de
vizinhos distintos na projeção simples não dirigida, não PageRank,
força ponderada ou quantidade de notícias. Não há lista manual de casos.

A vista inicial mostra até max_nos entidades por grau. Ao selecionar uma
entidade no combobox Vista ou na busca, abre-se sua vizinhança de um salto,
limitada por peso do par, grau e ID. Pares entre nós escolhidos são
limitados por peso, priorizando os incidentes ao foco. Limites são
visuais, não filtros científicos. Nós sem ligação visível podem resultar
da poda. Entrar ou sair de uma seleção não é entrar ou sair da rede.
A busca inclui todas as 27.642 entidades da série. Resultados exibem tipo
e ID para distinguir homônimos. O texto e o ID selecionado persistem
ao mudar de ano; ausência anterior é informada, sem inventar grau zero.
As listas do ranking são recalculadas pelo ano escolhido.

Todos os nomes estão inicialmente visíveis. A opção de desmarcá-los
preserva nomes dos destaques e da entidade acompanhada para reduzir
sobreposição. Preenchimento indica tipo; a entidade acompanhada ganha
borda vermelha e halo discreto, sem aumento de raio ou rótulo; as correspondências da busca
na vista também ganham borda vermelha. Contorno escuro indica destaque.
Raio visual r=min(35,8+2,5*ln(1+k)); sem acréscimo para a busca. O tamanho não é diretamente proporcional ao grau.
A mesma transformação é usada em todos os anos. Não é escala de área
proporcional nem distância semântica. Espessura usa ocorrências do par.

A física ForceAtlas2Based inicia ativada e pode ser desativada; a opção
é mantida ao trocar de ano ou vista. Restaurar posições desativa a
física e recupera as âncoras. As posições iniciais dos nós que aparecem
nas vistas globais de referência e nos cinco principais focos finais
usam disposição por componentes com semente 42 e pesos finais log1p,
seguida de compressão radial asinh(r/40). As demais posições iniciais
usam círculo determinístico por ID, sendo reorganizadas pela física.
É uma apresentação retrospectiva. Mover nós não altera o grafo ou
qualquer métrica. A física faz a comparação espacial entre anos exigir
cautela; desligá-la e restaurar posições facilita a inspeção.

O HTML incorpora dados completos dos cortes e calcula subgrafos no
navegador, permitindo pesquisar entidades fora dos destaques. Todas
as notícias de suporte dos objetos escolhidos podem ser consultadas
até o ano do corte, com exemplos, busca, paginação e CSV. O CSV inclui
a lista completa da seleção, mesmo com busca textual ativa. Notícias
de nós exigem participação em relação retida por padrão; a opção
adicional inclui menções com NER mesmo sem RE concluída. Títulos,
links, categorias e atributos são preservados; textos integrais não
são incorporados. Links abrem apenas por ação do usuário.

Composição dirigida e tipada dos pares é preservada para inspeção;
a representação visual permanece não dirigida ponderada. Cores são
tipos, não comunidades. Não há detecção de comunidades temporais,
novas relações, fusões de entidades ou correção de tipos nesta etapa.
A classificação herdada de EUA como ORGANIZACAO continua sendo uma
limitação a corrigir nos dados de origem em edição própria; não existe
reclassificação cosmética no HTML. Os indicadores são os da edição
conferida. Cobertura e volume anual contextualizam o crescimento.
Em 2021 não há RE concluída e a topologia repete 2020.

Recursos estão incorporados: não há CDN, fetch, API ou Neo4j para
explorar o HTML. Dados compactos usam índices locais para notícias,
pares e rótulos, com catálogos para recuperar seus identificadores
originais. As tabelas exportadas preservam os identificadores científicos.
O HTML cresce por incluir a série e a rastreabilidade completas; isso
evita carregar milhares de arquivos ou depender de servidor local.
As figuras estáticas são seleções de apresentação: seis cortes globais
e os cinco maiores graus finais, sem restringir os outros anos no HTML.
