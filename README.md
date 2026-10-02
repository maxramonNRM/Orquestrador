# Orquestrador

Framework em Python/Selenium para **coletas web de vários sites**, em que cada site é um **módulo (bot)** carregado dinamicamente por um **orquestrador único**. Inclui tentativas automáticas, tratamento e classificação de erros e padronização/validação dos dados com Pandas.

> Projeto de estudo. Use apenas em sites e dados públicos, respeitando os termos de uso de cada site e evitando sobrecarregar os servidores.

## O problema

Quando existem várias coletas separadas, cada uma com seu script, o código se repete, os erros são tratados de formas diferentes e os dados chegam em formatos diferentes. O orquestrador resolve isso centralizando a execução, o tratamento de falhas e a padronização da saída, e deixa cada site isolado em seu próprio módulo.

## Como funciona

1. O orquestrador identifica quais bots (módulos de sites) devem rodar e os **carrega dinamicamente**.
2. Cada bot executa a coleta do seu site.
3. Se ocorrer um erro, ele é **tratado e classificado**, e a coleta é **repetida automaticamente** quando faz sentido.
4. Os dados de todos os bots passam por uma etapa de **padronização e validação** com Pandas: valores nulos, duplicidades e EANs inválidos.
5. O resultado final é salvo em **CSV** ou **parquet**.

## Principais recursos

- **Um módulo por site:** adicionar ou remover um site não exige mexer no restante do código.
- **Retentativas automáticas** para falhas pontuais.
- **Classificação de erros**, para separar problemas temporários de problemas que exigem ajuste no bot.
- **Padronização e validação dos dados**: nulos, duplicidades e EANs inválidos.
- **Saída em CSV e parquet.**

## Tecnologias

Python, Selenium, Pandas.

## Estrutura do projeto

```
[PREENCHER: cole aqui a estrutura de pastas e arquivos do projeto,
 por exemplo: o arquivo do orquestrador, a pasta dos bots, a pasta de saída]
```

## Como rodar

1. Tenha o Python e o Google Chrome instalados.

2. Instale as dependências:

   ```
   pip install selenium pandas pyarrow
   ```

   O `pyarrow` é necessário para gerar a saída em parquet.

3. Execute o orquestrador:

   ```
   [PREENCHER: comando para rodar, por exemplo python orquestrador.py]
   ```

4. Os arquivos de saída serão gerados na pasta indicada acima.

## Como adicionar um novo site

**[PREENCHER: explique em 3 ou 4 passos como criar um novo bot, por exemplo copiar o módulo de um site existente, ajustar a coleta e confirmar o nome para o orquestrador carregar]**

## Limitações

- Cada bot depende da estrutura do site de origem: se o layout mudar, é preciso ajustar o módulo daquele site.
- A validação de EAN cobre os casos tratados no código e não substitui a conferência com a base de produtos.

## Próximos passos

- Agendamento automático das execuções.
- Log estruturado das coletas e dos erros.
- Testes automatizados para os módulos de validação.
