# MO438 — Redes de entidades em notícias sobre inteligência artificial

**Análise estrutural, comparativa e temporal de redes construídas a partir de notícias brasileiras.**

Projeto da disciplina **MO438 — Redes Complexas**, do Instituto de Computação da Universidade Estadual de Campinas (IC/Unicamp), no segundo semestre de 2026.

**Autor:** Pedro Henrique de Carvalho Godoy  
**Professor da disciplina:** Ruben Interian

## Objetivo

Analisar comparativamente e ao longo do tempo redes de entidades extraídas de notícias sobre inteligência artificial de diferentes fontes jornalísticas, utilizando a caracterização global como referência.

O projeto transforma notícias de **G1, Folha de S.Paulo e CNN Brasil** em redes de pessoas, organizações e locais, conectados pelas relações semânticas extraídas dos textos. A análise examina conectividade, componentes, centralidades, comunidades, crescimento e concentração de visibilidade.

## Recortes da análise

| Frente | Dados considerados | Pergunta principal |
|---|---|---|
| Rede global | Três fontes, com relações disponíveis entre 1994 e 2025 | Como se organiza a estrutura relacional do conjunto observado? |
| Comparação entre fontes | Redes separadas de G1, Folha e CNN Brasil em 2025 | Quais características e entidades centrais são compartilhadas ou distintas? |
| Evolução temporal | 32 cortes anuais acumulados da Folha, de 1994 a 2025 | Como crescem as conexões e mudam os protagonistas? |

Um corte acumulado reúne os registros até o ano indicado. A rede global utiliza todos os períodos com relações disponíveis; a comparação entre fontes é restrita a 2025.

## Principais resultados

Os números abaixo correspondem à edição de análise de **20 de novembro de 2026**. Novas extrações de relações não são incorporadas automaticamente a esses resultados.

| Indicador | Rede global |
|---|---:|
| Notícias selecionadas no acervo de entrada | 23.657 |
| Notícias que sustentam relações na rede | 9.113 |
| Entidades participantes | 40.627 |
| Pares na projeção simples não dirigida | 57.536 |
| Arestas dirigidas, diferenciadas por tipo de relação | 83.188 |
| Grau médio na projeção simples | 2,8324 |
| Componentes conexas | 3.259 |
| Entidades na maior componente conexa (GCC) | 32.575 (80,18%) |
| Distância média na GCC | 4,8596 |
| Diâmetro na GCC | 20 |

A rede é esparsa e heterogênea: a maioria das entidades tem poucos vizinhos, enquanto um grupo menor concentra conectividade e presença documental. As fontes compartilham protagonistas, mas apresentam baixa sobreposição de pares. Na série temporal, aproximadamente metade dos pares novos conecta uma entidade já presente a uma nova entidade.

A visibilidade documental conta uma vez cada entidade em cada notícia na qual ela participa de relações incorporadas. Aproximadamente 1% das entidades concentra **35,07% das aparições entidade–notícia** da rede global. Essa proporção se refere às aparições, não à quantidade de notícias exclusivas desse grupo.

### Exemplos de trajetórias temporais

![Graus acumulados de seis entidades na Folha, separados em locais, organizações e pessoas](docs/figuras/trajetorias_seis.png)

As curvas acompanham os mesmos seis casos discutidos na análise global. Os painéis têm escalas verticais próprias. A faixa cinza marca 2021, sem novas relações incorporadas por falta de RE. USP significa Universidade de São Paulo; Lula corresponde ao grupo Luiz Inácio Lula da Silva. A cobertura desigual de extração limita a interpretação dos saltos de crescimento.

## Metodologia

1. **Preparação e auditoria:** conferência de notícias, datas, fontes, textos e identificadores documentais.
2. **Reconhecimento de entidades (NER):** identificação de pessoas, organizações e locais.
3. **Extração de relações (RE):** identificação de vínculos semânticos entre entidades, com registro da cobertura e dos resultados parciais.
4. **Integração de entidades e relações:** associação das menções aos grupos consolidados e construção das redes com evidências documentais.
5. **Análise global e por fonte:** estrutura, distâncias, grau, força, PageRank e comunidades por Louvain e Leiden.
6. **Análise temporal:** crescimento, formação e reforço de conexões, persistência nos rankings, distribuições de graus e associação entre grau anterior e novos vizinhos.

O **grau** conta vizinhos distintos. A **força** soma os pesos das relações incidentes. O peso registra a recorrência das relações extraídas e não equivale necessariamente a notícias distintas ou fatos independentes. As distâncias são medidas na GCC, pois a rede completa é desconexa.

## Organização do código

Os caminhos abaixo consideram a pasta `PROJECT` como raiz do repositório. Os módulos permanecem junto ao notebook para preservar os imports utilizados na implementação.

| Caminho | Conteúdo |
|---|---|
| `Pipeline_Noticias_IA.ipynb` | Notebook principal e execução por etapas. |
| `ner_dados.py` | Leitura e consolidação das anotações de entidades. |
| `re_execucao.py`, `re_parser.py`, `re_posprocessamento.py`, `re_consolidacao.py` | Execução, validação e consolidação da extração de relações. |
| `entidades_integracao.py` | Integração com os grupos de entidades consolidados. |
| `redes_*.py` | Construção, projeções e análises da rede global e dos recortes. |
| `fontes_*.py` | Análises comparativas por fonte. |
| `temporal_*.py` | Construção, análise e visualização da série temporal. |
| `neo4j_*.py` | Integração e carga no Neo4j. |
| `testar_*.py` | Verificações computacionais dos módulos. |
| `documentacao/` | Métodos, entradas, parâmetros e instruções específicas das etapas. |
| `dados/` | Entradas e dados processados, conforme disponibilidade de distribuição. |
| `resultados/` | Tabelas, gráficos, manifestos e pacotes de resultados. |
| `relatorio/` | Relatório, fontes LaTeX e figuras. |

## Instalação e execução

Utilize **Python 3.11 ou superior** em um ambiente virtual. Na raiz do projeto:

```bash
python -m venv .venv
```

Ative o ambiente no Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Ou no Linux/macOS:

```bash
source .venv/bin/activate
```

Instale as dependências de base:

```bash
python -m pip install -r requirements.txt
```

As etapas de redes também utilizam os pacotes abaixo; a comparação de caudas desta edição empregou `powerlaw` 1.5:

```bash
python -m pip install neo4j scipy networkx pyvis "powerlaw==1.5"
```

Para reproduzir uma execução específica, confira também as versões registradas nos arquivos `ambiente.json` dos resultados. Os comandos acima preparam as dependências, mas não fixam integralmente o ambiente de todas as etapas.

Inicie o JupyterLab:

```bash
python -m jupyterlab
```

Abra `Pipeline_Noticias_IA.ipynb` e execute as etapas necessárias ao recorte desejado, respeitando suas dependências. Evite executar o notebook inteiro sem revisar as células que habilitam extrações, carga no banco ou novas análises.

### O que cada modalidade exige

| Modalidade | Requisitos |
|---|---|
| Consultar o relatório e resultados exportados | Arquivos finais correspondentes à edição analisada. |
| Reproduzir análises locais | Entradas consolidadas, manifestos, módulos e dependências da etapa. |
| Executar algoritmos no Neo4j GDS | Banco e plugin GDS configurados, com as projeções verificadas. |
| Realizar novas extrações NER/RE | Textos, prompts, configurações e credenciais do provedor escolhido; pode gerar cobrança. |

As execuções comunitárias registradas nesta edição utilizaram **Neo4j GDS 2026.09.0**. Consulte a documentação de cada etapa para sua configuração.

Para RE, mantenha `EXECUTAR_RE=False` durante a conferência inicial. As instruções estão em [Configuracao_RE.md](Configuracao_RE.md). Credenciais pertencem à configuração local e não devem ser publicadas.

## Dados e reprodução

O corpus selecionado de entrada abrange 1994–2026, mas as relações da rede global desta edição vão até 2025. Entre as 9.113 notícias de suporte, 6.511 são de 2025 e 2.602 são de outros anos.

A execução requer arquivos de entrada compatíveis com as assinaturas registradas nos manifestos, incluindo a base preparada de notícias, as menções consolidadas, o registro de entidades e as relações do recorte. O código, sozinho, não reconstrói resultados idênticos sem essas entradas.

Os textos jornalísticos, dados volumosos, checkpoints e bancos locais têm disponibilização separada do código. Consulte as instruções e os manifestos da etapa antes de substituir entradas. Não é necessário fazer novas chamadas de extração para consultar resultados já exportados.

## Limitações

- Os resultados descrevem o acervo coletado e processado, não toda a produção jornalística nem a opinião pública.
- A cobertura de RE varia entre anos. Em 2021 não foram incorporadas relações; 2020 e 2024 apresentam baixa cobertura na série da Folha.
- Os cortes acumulados mantêm conexões anteriores e não representam sua dissolução. A identificação das entidades usa informações do corpus completo.
- NER, RE e resolução de entidades estão sujeitos a erros. Centralidade não mede diretamente poder, influência ou posição editorial.
- Algumas execuções de Leiden retornaram comunidades desconexas. O diagnóstico reproduziu esse comportamento, sem estabelecer sua causa; as partições e as ressalvas foram preservadas.
- Os ajustes de cauda e a associação temporal são descritivos e não demonstram, por si, uma rede livre de escala ou um mecanismo causal de vantagem cumulativa.

## Relatório e trabalhos relacionados

O relatório da edição analisada fica em `relatorio/relatorio.pdf`, acompanhado da fonte LaTeX e das figuras.

O projeto dá continuidade à pesquisa do autor e ao trabalho publicado com Ruben Interian:

> GODOY, Pedro Henrique de Carvalho; INTERIAN, Ruben. Relação IA-sociedade representada na mídia: construção e análise multidisciplinar de redes de entidades nomeadas a partir de textos de notícias. In: *Anais do X Encontro de Teoria da Computação (ETC 2025)*. Sociedade Brasileira de Computação, 2025. p. 70–74. [DOI: 10.5753/etc.2025.8915](https://doi.org/10.5753/etc.2025.8915).

> GODOY, Pedro Henrique de Carvalho. *Relação IA-sociedade representada na mídia: construção e análise multidisciplinar de redes de entidades nomeadas identificadas em notícias*. 2026. Dissertação (Mestrado em Ciência da Computação) — Instituto de Computação, Universidade Estadual de Campinas, Campinas, 2026.

Os conceitos da disciplina estão nos [materiais da MO438 — Redes Complexas, segundo semestre de 2026](https://ic.unicamp.br/~ruben/2026/S2-MO438/).

## Como citar

Para citar esta implementação, utilize os metadados de [CITATION.cff](CITATION.cff). Ao discutir os trabalhos anteriores, cite o artigo ou a dissertação correspondente. O DOI do artigo identifica o artigo de 2025, não uma versão deste software.

## Autoria e contato

Desenvolvido por **Pedro Henrique de Carvalho Godoy**, no contexto da disciplina MO438 do IC/Unicamp. Professor da disciplina e orientador da pesquisa de origem: **Ruben Interian**.

Perfil do autor: [github.com/PedroHCGodoy](https://github.com/PedroHCGodoy/).
