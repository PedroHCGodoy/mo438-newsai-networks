# Inspeção e integração com Neo4j

A inspeção verifica o ambiente de execução e registra as condições do banco antes da importação de uma rede versionada. Não altera dados, restrições, índices ou projeções GDS.

## Entradas

- Rede ativa, seus hashes e referências às etapas anteriores, conferidos por `carregar_rede`.
- Configuração local em `.env`: NEO4J_URI, NEO4J_USER (ou NEO4J_USERNAME), NEO4J_PASSWORD e, opcionalmente, NEO4J_DATABASE. O padrão de banco é `neo4j`.
- Instância Neo4j iniciada e acessível a partir do ambiente Jupyter.

As credenciais não são gravadas no relatório, no console ou no pacote de verificação. A URI não deve conter usuário/senha. O arquivo `.env` não é alterado pelo módulo.

## Consultas

A implementação usa o driver Python oficial, `verify_connectivity`, sessões com banco explícito e transações `execute_read`. As consultas são fixas, sem interpolação de configurações em Cypher.

São consultados:

1. Componentes e versões do servidor.
2. Quantidades de nós e relações existentes no banco.
3. Redes existentes nos rótulos Entity/NewsAIEntity, agrupadas por graph_tag e rótulos; até 100 grupos são listados.
4. Restrições de unicidade e outros tipos de restrição visíveis ao usuário.
5. Índices e seus estados.
6. Presença de dados com o graph_tag proposto para a rede selecionada.
7. Versão GDS e nomes das funções/procedimentos acessíveis.
8. Catálogo de projeções GDS visíveis, com até 100 entradas.

Os totais gerais podem incluir objetos de outros projetos: não são contagens da rede selecionada. Falhas de permissão ou funções indisponíveis são registradas como UNAVAILABLE, sem executar alternativas que modifiquem o banco. Uma capacidade não localizada pode estar ausente ou inacessível ao usuário conectado; não é suficiente para diagnosticar qual dessas causas ocorreu.

O inventário não estima a memória disponível para os algoritmos. As estimativas de memória e o suporte efetivo das projeções serão verificados nas etapas correspondentes. A carga e as projeções ainda não são executadas por este módulo.

## Dados existentes

Vestígios não são apagados. O identificador proposto é `newsai_<20 caracteres da assinatura da rede>`, para separar as edições. A inspeção registra se já existem nós ou relações com essa identificação. Essa identificação não substitui a análise de restrições globais sobre os rótulos de nós: uma restrição antiga de nome ou de ID isolado pode interferir em uma nova importação.

A etapa de carga será preparada a partir do inventário, mantendo o modelo de entidades e relações dirigidas e considerando a compatibilidade do esquema existente. Nenhum procedimento de limpeza ou `DETACH DELETE` é incluído nesta inspeção.

## Saídas

`resultados/neo4j/Conferencia_Neo4j_<data>_<identificador>.json` registra a conferência. O pacote `Resumo_Ambiente_Neo4j_....zip` contém somente esse relatório.

`inspection_complete` indica que as consultas essenciais ao inventário do banco foram concluídas. Não significa aprovação da carga nem disponibilidade de todos os algoritmos GDS. `load_executed` permanece falso e `database_writes` permanece zero nesta etapa.

## Referências técnicas

- Driver Python: https://neo4j.com/docs/python-manual/current/connect/
- Transações: https://neo4j.com/docs/python-manual/current/transactions/
- Inventário de procedimentos: https://neo4j.com/docs/operations-manual/current/procedures/show-procedures/

A disponibilidade concreta será registrada a partir das versões instaladas no ambiente de execução. Testes com transporte simulado não substituem essa conferência.
