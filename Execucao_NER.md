# Reconhecimento de entidades nomeadas

O notebook principal contém um fluxo de extração integral, com checkpoint, validação e exportação. Dados de anotações fornecidos como entrada possuem proveniência própria e podem ser carregados sem executar inferências. Operações específicas de adaptação de um acervo não integram esse fluxo.

## Leitura dos dados disponíveis

A seção 15 é independente das demais células e de credenciais. Ela confere os hashes dos arquivos em `dados/processados/ner/consolidado`, as contagens e a cobertura documental. Quando a base preparada está disponível, compara as identidades, versões e textos de entrada, sem exigir a mesma serialização física do CSV.

`mencoes_todas.csv.gz` reúne as dez categorias. `mencoes_pol.csv.gz` é o subconjunto PESSOA, ORGANIZACAO e LOCAL. Leia os arquivos em blocos para reduzir memória. Relacione as menções a `documentos_ner.csv` por `news_id` antes de selecionar estados.

| Campo/estado | Interpretação |
|---|---|
| AVAILABLE | Anotações disponíveis; consultar também a origem e a base de completude. |
| PARTIAL | Menções aproveitáveis com pendências ou resposta interrompida. |
| UNAVAILABLE | Houve tentativa, mas não há resultado aproveitável. |
| NOT_PROCESSED | Nenhum resultado desta seleção de fontes foi incorporado. |
| execution_state=IMPORTED | Anotações fornecidas como entrada; não são chamadas desta execução. |
| completion_basis=artifact_compatible_completeness_unknown | Compatibilidade técnica; completude original desconhecida. |
| input_source | Identificador da fonte descrita no manifesto. |

AVAILABLE não significa que todas as entidades tenham sido reconhecidas. SUCCESS descreve validação operacional, e não precisão ou revocação semântica. Nenhuma métrica de qualidade linguística é inferida apenas pelo alinhamento literal.

## Nova execução integral

1. Prepare/carregue `df_news` nas seções 9 e 10.
2. Confira a seção 16: período, limite por lote, paralelismo e caminhos.
3. Carregue as funções na seção 17 e rode os testes locais da seção 18.
4. Para chamadas reais, crie `.env` a partir de `.env.example`, configure `GEMINI_API_KEY` e, opcionalmente, `KEY_NAME`. Habilite `EXECUTAR_NER=True` na seção 16 e execute a seção 19.
5. Exporte na seção 20. Após concluir o período desejado, a seção 21 pode consolidar essa exportação em um destino novo.

A fila integral contém todas as notícias da base, independentemente dos snapshots. Por isso, esta execução pode gerar novas cobranças para notícias que já possuem anotações em outra fonte. Manter `EXECUTAR_NER=False` evita chamadas. `MODO_NER='PILOTO'` seleciona até cinco entradas com diversidade de fontes e tamanhos; `'FILA'` utiliza o período selecionado. `LIMITE_CHAMADAS_NER` limita novas tentativas por invocação, incluindo falhas. `TRABALHADORES_NER` varia de 1 a 5.

O padrão `ANO_MAXIMO_NER=2025` seleciona o período central. `None` inclui todos os anos. Textos idênticos compartilham requisição, mas preservam vínculos com cada notícia.

## Contrato e interpretação

O texto é `title.strip() + '\n\n' + full_text.strip()`, usando apenas a parte não vazia quando necessário. A descrição não é adicionada. O template em `dados/originais/ner/prompt_ner.txt` é enviado literalmente, sem mensagem de sistema adicional ou esquema de resposta que altere o contrato.

- Modelo: `gemini-2.5-flash`.
- Temperatura: 0; semente: 42; MIME: `application/json`.
- SHA-256 do prompt: `87a4d970256b1e1301d0f84f22055a554439175db2082ed3c0db27505df86a82`.
- Categorias: PESSOA, ORGANIZACAO, LOCAL, TEMPO, ACONTECIMENTO, OBRA, VALOR, COISA, ABSTRACCAO, OUTRO.

Manter os parâmetros e o prompt documenta o procedimento; respostas futuras de um serviço externo podem variar. O parser aceita as estruturas JSON documentadas no código e registra reparos sintáticos limitados. Respostas interrompidas preservam somente objetos completos, sempre com estado PARTIAL. Rótulos, superfícies e posições originais permanecem nos arquivos, junto com as transformações.

## Persistência e falhas

O checkpoint da execução integral fica em `dados/processados/ner/execucao_integral/checkpoint.sqlite`. Preserve essa pasta para retomar em outro kernel. Exportar não substitui o checkpoint: o ZIP serve para inspeção e consolidação, mas não é o banco usado na retomada.

Cada log informa identificadores de requisição/tentativa. ENVIO indica início da tentativa HTTP; RETORNO informa código e tempo; VALIDAÇÃO informa o estado do conteúdo. HTTP 200 confirma resposta de transporte, sem garantir um JSON NER válido.

Falhas individuais ficam registradas sem repetição automática. A execução suspende novos envios após a sequência configurada de falhas ou um erro imediato de configuração, autenticação ou quota. Requisições em andamento são concluídas. PARTIAL não conta como falha consecutiva, mas continua pendente de revisão.

A revalidação local de respostas salvas utiliza o checkpoint desta execução, faz backup quando necessário e não chama a API. Ela é uma verificação do executor, distinta da adaptação de anotações externas.

## Consolidação e snapshots

`ner_dados.py` valida cada menção contra a versão da notícia, o hash de entrada, o rótulo, o intervalo literal e seu identificador. Fontes sobrepostas são rejeitadas: escolher entre versões exige uma seleção explícita. Campos de origem são preservados. Parciais são incorporados com estado documental, sem promovê-los a resultados completos.

A seção 21 consolida a exportação da execução corrente. Alternativamente, na pasta do projeto:

```bash
python ner_dados.py --base dados/processados/noticias_preparadas.csv --exportacao resultados/execucao/ner_integral/Resultados_NER.zip --destino dados/processados/ner/consolidado_execucao
```

O destino deve ser novo. Os arquivos são preparados em pasta temporária e disponibilizados juntos. O manifesto registra fontes, hashes, contagens e políticas. Anotações importadas, quando utilizadas, devem ter fonte, contexto e autoria documentados conforme a evidência disponível; informações desconhecidas devem permanecer explícitas.

Para testar o módulo sem rede:

```bash
python testar_ner_dados.py
```
