# Diagnóstico e recuperação do alinhamento NER

## Evidências examinadas

Foram examinadas as 11 tentativas exportadas em `Resultados_NER.zip`. O SHA-256 do arquivo recebido é `087efd7f00921e3f7fd5122601daadea0ddab8d6dd3c9099b9b85e46e9f6b51c`.

Todas retornaram HTTP 200, um candidato terminado com STOP, JSON NER válido e o modelo efetivo gemini-2.5-flash. O template registrado tem o mesmo hash literal de referência. Portanto, as rejeições observadas não foram erros de autenticação, falhas HTTP ou JSON malformado: o diagnóstico inicial era uma ocorrência textual ausente ou ambígua nos índices apresentados pelo modelo.

A política anterior rejeitava o documento inteiro ao encontrar uma única ambiguidade. Esse critério descartava também as menções que podiam ser alinhadas e era inadequado para preservar e aproveitar as respostas recebidas.

## Exemplo verificável

Na notícia sobre tradução de voz em Facebook e Instagram, o modelo indicou Facebook nos índices 36 a 44. A fatia correspondente era `ra Faceb`; a ocorrência no título começa no índice 39. O nome aparece também em outros trechos. Assim, buscar apenas uma ocorrência global única não resolve esse registro.

Há ainda excesso de previsões em algumas superfícies: uma resposta apresentou quatro registros de Instagram para três ocorrências literais; outra, quatro de YouTube para três. A recuperação não inventa uma quarta posição nem escolhe arbitrariamente uma posição para todos esses casos.

## Política corrigida

O prompt e os parâmetros de geração não foram modificados. A correção é local e usa os textos efetivamente enviados e as respostas já salvas.

As menções são examinadas individualmente. Podem ser alinhadas por fatia literal exata, um limite inequívoco, ocorrência única ou correspondência de todas as ocorrências quando o número de registros do mesmo nome/categoria coincide com o conjunto de ocorrências e as âncoras são compatíveis. A última regra é identificada como OCCURRENCE_COUNT_MATCH; pressupõe correspondência entre os registros previstos e todas as ocorrências encontradas. Não é uma prova semântica de correção da categoria ou de completude do reconhecimento.

Registros ainda ambíguos mantêm o objeto original e a lista de posições candidatas. A distância entre o índice sugerido e uma ocorrência não é usada para selecionar arbitrariamente uma posição.

## Resultado do reprocessamento local

| Resultado | Quantidade |
|---|---:|
| Registros de entidades devolvidos pelo modelo | 352 |
| Menções alinhadas e conferidas por fatia literal | 270 |
| Registros pendentes para revisão | 82 |
| Documentos com todos os registros tratados | 3 |
| Documentos parciais | 8 |
| Novas chamadas ao modelo | 0 |

Das 270 menções alinhadas, 57 pertencem aos três documentos completos e 213 aos oito documentos parciais. No recorte Pessoa/Organização/Local, há 97 menções alinhadas e 44 pendências. Essas quantidades são ocorrências e registros, não entidades distintas.

As ações aplicadas foram 8 fatias originalmente exatas, 3 correções apoiadas por um dos limites, 161 correspondências literais únicas e 98 correspondências pelo conjunto completo de ocorrências. Todas as 270 fatias foram verificadas contra a entrada exata de sua requisição. Não foi feita avaliação semântica dos rótulos.

As respostas brutas foram preservadas byte a byte e continuaram existindo exatamente 11 tentativas. O diagnóstico foi reproduzido em um banco temporário reconstruído com os dados exportados. O checkpoint original no computador do pesquisador não foi alterado por essa análise; a atualização do executor permite aplicar a mesma revalidação nesse banco local.

SUCCESS significa tratamento completo da resposta segundo a política textual; PARTIAL preserva menções recuperadas e pendências sem declarar o documento integralmente validado. Nenhum dos dois estados é fabricado a partir de uma falha de API.

## Prioridade até 2025

O recorte até 2025 contém 681 notícias/requisições da fila pendente inicial. As 5.678 notícias de 2026 ficam adiadas, em 5.677 requisições únicas. O filtro de execução não remove registros ou altera o dataset.

Após essa recuperação, o recorte tem 3 requisições integralmente tratadas, 8 parciais e 670 ainda não executadas. As respostas parciais não são reenviadas automaticamente ao modelo. A revisão do alinhamento deve usar primeiro o material já recebido, sem uma nova geração paga para o mesmo problema.

## Verificação e aplicação

A implementação passou por 57 testes offline, além da regressão com as 11 respostas recebidas. Os testes cobrem recuperação, preservação do número de tentativas, idempotência, ambiguidades, correspondência por contagem, filtragem temporal e exportação.

Aplique a atualização preservando o checkpoint local. Reinicie o kernel, carregue a seção 20, mantenha EXECUTAR_NER=False e ANO_MAXIMO_NER=2025 na seção 21 e execute 21, 22, 24 e 25. A revalidação cria uma cópia de segurança antes de atualizar os estados, sem ler a chave e sem gerar chamadas.

O material recuperado inclui menções completas, menções parciais e pendências em arquivos separados. Ele é evidência para revisão; as menções parciais não devem ser incorporadas silenciosamente como documentos completos aos experimentos de redes.
