# Migrate MTAX

Converte os sistemas de um servidor MTA para o MTAX. Este é o mesmo conversor usado no site, então você pode conferir o código e rodar tudo no seu próprio PC, sem enviar nenhum arquivo para ninguém.

## Como usar

1. Instale o [Python](https://www.python.org/downloads/) 3.12 ou mais novo. No instalador, marque **Add Python to PATH**.
2. Baixe este repositório: botão verde **Code**, depois **Download ZIP**, e extraia.
3. Coloque seu servidor na pasta `ENTRADA`. Pode ser a pasta do servidor, várias pastas, ou arquivos `.zip` e `.tar`.
4. Dê dois cliques em `MIGRAR.bat`.
5. Pegue o resultado na pasta `SAIDA`. Cada servidor sai em uma pasta própria, com um `relatorio.txt`.

Seus arquivos originais em `ENTRADA` não são alterados. O programa só usa a internet para buscar a versão atual da camada de compatibilidade no repositório oficial do MTAX. Sem conexão, ele usa o `camada_mta.json` incluído aqui.

## O que sai em SAIDA

- `resources`: sistemas prontos para o MTAX.
- `databases`: bancos `.db` e `.sqlite` dos sistemas. Copie para a pasta do servidor, junto do `server.cfg`.
- `[COMPILADOS]`: sistemas compilados, que não dá para converter. Entre em contato com a loja responsável.
- `[MODELOS-CRIPTOGRAFADOS]`: modelos criptografados. Entre em contato com a loja responsável ou, se foi encomenda, peça os modelos sem criptografia.
- `[HYPER]`: sistemas da Hyper Scripts, que não passam pela conversão.

## Pasta [COMPILAR]

Para sistemas que ainda vão passar pelo compilador, coloque-os em `ENTRADA/[COMPILAR]`. Eles saem com as linhas `:mta` comentadas no manifest.

## Site

A pasta `site` tem o site, que roda o mesmo `migrar.py` no navegador. Depois de alterar o conversor, rode `site/ATUALIZAR-CONVERSOR.bat`.
