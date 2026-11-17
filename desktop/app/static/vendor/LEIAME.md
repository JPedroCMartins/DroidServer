# Bibliotecas do painel (cópias locais)

O painel não depende de internet: estas bibliotecas são servidas pelo próprio
Host (`/static/vendor/...`). Versões fixas, as mesmas usadas antes via CDN:

| Arquivo | Origem | Licença |
|---|---|---|
| `tailwind-3.4.17.js` | https://cdn.tailwindcss.com/3.4.17 (Tailwind CSS, modo script) | MIT |
| `xterm-5.3.0.js`, `xterm-5.3.0.css` | npm `xterm@5.3.0` | MIT |
| `xterm-addon-fit-0.8.0.js` | npm `xterm-addon-fit@0.8.0` | MIT |
| `socket.io-4.7.2.min.js` | https://cdn.socket.io/4.7.2/socket.io.min.js | MIT |
| `fonts/poppins-latin-*.woff2`, `poppins.css` | npm `@fontsource/poppins@5.1.0` | SIL OFL 1.1 |

Para atualizar, baixe a nova versão, troque o nome do arquivo e o `<head>` de
`templates/index.html`.
