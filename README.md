# Redes de entidades em notícias sobre inteligência artificial

Autor: Pedro Henrique de Carvalho Godoy.

Pipeline Python/Jupyter para auditoria, preparação, caracterização de corpus e reconhecimento de entidades em notícias brasileiras sobre inteligência artificial. Preserva dados originais e registra identidades documentais, versões textuais, parâmetros e proveniência. Extração de relações e análises de redes serão disponibilizadas em etapas posteriores.

## Instalação

Requer Python 3.11 ou superior. Na pasta do projeto:

```bash
python -m pip install -r requirements.txt
python -m jupyterlab
```

Abra `Pipeline_Noticias_IA.ipynb`. Há um único notebook principal; `ner_dados.py` fornece funções reutilizáveis de consolidação e leitura.

## Organização

| Caminho | Conteúdo |
|---|---|
| dados/originais/ | Corpus, dicionário editorial e prompt NER. |
| dados/processados/ | Base preparada e checkpoint da extração. |
| dados/processados/ner/consolidado/ | Snapshot de menções, cobertura e proveniência. |
| resultados/tabelas/ | Estatísticas e verificações. |
| resultados/figuras/ | Figuras em SVG, PNG e PDF. |
| resultados/execucao/ | Manifestos e exportações de execuções. |
| resultados/redes/ | Destino dos grafos derivados. |
| relatorio/ | Destino do relatório científico. |

## Etapas

As seções 1 a 8 auditam esquema, datas, textos, duplicidades e cobertura editorial. As seções 9 e 10 preparam e carregam a base com identificadores estáveis. As seções 11 a 14 caracterizam volume, categorias, assinaturas de autoria e tamanho dos textos.

A seção 15 carrega e verifica anotações NER disponíveis, inclusive em um kernel novo. As seções 16 a 20 implementam configuração, validação, testes, execução integral e exportação. A seção 21 consolida uma exportação em um snapshot novo. Consulte `Execucao_NER.md` antes de habilitar chamadas.

Dados importados têm proveniência própria. Sua disponibilidade não indica que tenham sido produzidos na execução integral deste notebook. Operações de compatibilidade específicas de um acervo são realizadas antes de sua incorporação como entrada tabular.

## Reprodutibilidade e interpretação

Os identificadores usam SHA-256 e independem da posição das linhas. Campos originais são preservados; candidatos a duplicidade não são excluídos automaticamente. Categorias editoriais são agrupadas por dicionário e não equivalem a temas inferidos do conteúdo. Autoria representa assinaturas registradas, incluindo unidades coletivas.

As contagens descrevem o corpus coletado, não toda a produção dos veículos ou a opinião pública. A cobertura de 2026 termina em junho; comparações anuais precisam considerar essa cobertura parcial.

O prompt NER é conferido por hash e enviado literalmente. O alinhamento de superfícies é heurístico e não substitui avaliação semântica. Dados disponíveis, resultados parciais e documentos sem processamento são distinguidos na cobertura.

Os testes locais verificam consistência computacional; não validam automaticamente hipóteses científicas. Credenciais pertencem ao `.env` local. Chamadas estão desativadas por padrão. Preserve o checkpoint para retomar a extração, e mantenha snapshots anteriores para comparar versões.

## Cores das fontes

| Fonte | Cor Matplotlib | Hexadecimal |
|---|---|---|
| CNN Brasil | tab:blue | #1f77b4 |
| Folha de S.Paulo | tab:orange | #ff7f0e |
| G1 | tab:green | #2ca02c |

## Limitações da resolução de entidades

O método de resolução está sujeito a ambiguidades de identidade e a limitações de recuperação e agrupamento. Essas ressalvas e os aprimoramentos previstos estão documentados em [Limitacoes_Resolucao_Entidades.md](Limitacoes_Resolucao_Entidades.md) e no notebook principal. O impacto nas análises de redes ainda não foi quantificado.
