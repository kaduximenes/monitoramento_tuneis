# Fontes da Prefeitura (Cera Pro)

O Manual de Marca Prefeitura Rio 2025 define a **Cera Pro** como fonte institucional.
Ela é uma fonte comercial (Typemates) e não está no repositório. Peça os arquivos à
comunicação da Prefeitura e coloque nesta pasta, em `.woff2`, com estes nomes:

| Arquivo | Peso | Uso no manual |
|---|---|---|
| `CeraPro-Regular.woff2` | 400 | textos longos |
| `CeraPro-Medium.woff2` | 500 | subtítulos e títulos curtos |
| `CeraPro-Black.woff2` | 900 | títulos (preferencialmente em caixa alta) |

Se você tiver `.otf` ou `.ttf`, converta para `.woff2`, por exemplo com
`pip install fonttools brotli` e depois
`python -c "from fontTools.ttLib import TTFont; f=TTFont('CeraPro-Black.otf'); f.flavor='woff2'; f.save('CeraPro-Black.woff2')"`.

Sem esses arquivos, o painel usa a **Outfit** (Google Fonts) automaticamente.
