# Orquestrador

Orquestrador genérico de **coletas web com Selenium**, em que cada site é um **módulo (bot)** carregado dinamicamente. O orquestrador cuida de tudo o que é comum (acessos, navegador, retentativas, tratamento de erros, padronização dos dados e saída), e cada bot só precisa saber coletar **um** site.

> Projeto de estudo e portfólio. Use apenas em sites e dados aos quais você tem acesso autorizado, respeitando os termos de uso de cada um.

## O problema

Com vários scripts de coleta separados, o código se repete, os erros são tratados de formas diferentes e os dados chegam em formatos diferentes. Centralizar a execução, o tratamento de falhas e a padronização deixa cada site isolado em seu módulo e a saída sempre no mesmo formato.

## Como funciona

1. O orquestrador recebe o **nome do bot** e a **região** na linha de comando.
2. Carrega dinamicamente o módulo `bot_<nome>.py` e a função `main_<nome>`.
3. Lê a planilha de acessos e filtra os registros do bot e da região (apenas os marcados para execução). A ordem dos estados é embaralhada a cada execução.
4. Para cada estado, abre o navegador (Microsoft Edge), chama o bot e tenta a coleta **até 10 vezes**.
5. Se ocorrer um erro, ele é **classificado**, uma **captura de tela** é salva para análise e a coleta é repetida.
6. Os dados passam pela **padronização e validação** com Pandas.
7. O resultado é gravado em **CSV** (consolidado da região) e em **parquet** (backup por estado).

## Principais recursos

- **Um módulo por site:** adicionar ou remover um site não exige mexer no orquestrador.
- **Retentativas automáticas**, com captura de tela do erro. Se a captura falhar, a próxima tentativa roda com o navegador visível.
- **Classificação de erros:**

  | Rótulo | Origem |
  |---|---|
  | Driver desatualizado | `SessionNotCreatedException` |
  | Elemento não encontrado | `NoSuchElementException` |
  | Elemento interceptado | `ElementClickInterceptedException` |
  | Erro de conexão | `ConnectionRefusedError` |
  | Erro de time out | `TimeoutException` |
  | Erro de login, captcha ou coleta | mensagens lançadas pelos próprios bots |
  | Erro desconhecido | demais casos |

- **Padronização e validação dos dados** (descrita abaixo).
- **Driver do navegador automático**, com driver local como alternativa.
- **Configuração por variáveis de ambiente:** nenhum caminho ou credencial fica no código.

## Padronização e validação

- Remoção de linhas duplicadas.
- Preços convertidos para número, exigindo pelo menos um preço válido (o preço final pode ser vazio, mas não zero).
- Descrição sem acentos, sem caracteres especiais e sem frases como "indisponível", em maiúsculas.
- **EAN** numérico, descartando códigos de teste (sequências de 7 dígitos iguais no início ou no fim).
- Quantidade por pacote igual a zero vira vazio.
- Arredondamento dos valores numéricos.
- Um único registro por combinação de EAN, concorrente e estado.

## Tecnologias

Python, Selenium (com selenium-wire), Pandas, webdriver-manager, unidecode, PyArrow, openpyxl.

## Estrutura do projeto

```
run_collector.py     # orquestrador
bot_<site>.py        # um módulo por site, com a função main_<site>
```

## Como rodar

1. Tenha o Python e o Microsoft Edge instalados.

2. Instale as dependências:

   ```
   pip install selenium selenium-wire webdriver-manager pandas unidecode pyarrow openpyxl
   ```

   Se der erro de importação no selenium-wire, fixe a versão com `pip install blinker==1.7.0`.

3. Defina as variáveis de ambiente:

   | Variável | Descrição |
   |---|---|
   | `COLLECT_USERS_FILE` | Planilha (.xlsx) com os acessos por site e estado |
   | `COLLECT_OUTPUT_DIR` | Pasta de saída dos CSV e parquet |
   | `COLLECT_SCREENSHOT_DIR` | Pasta das capturas de tela de erro |
   | `COLLECT_DOWNLOAD_DIR` | Pasta base de downloads do navegador |
   | `COLLECT_DRIVER_PATH` | (opcional) caminho de um `msedgedriver.exe` local |

4. Monte a planilha de acessos com as colunas: `Executar`, `Site`, `Região`, `Usuario`, `Senha`, `Licenca`, `Roda em tela`, `Navegacao anonima`, `IdUsuario`, `Estado` e `Website`. **Essa planilha contém senhas e não deve ser enviada ao GitHub.**

5. Execute:

   ```
   python run_collector.py <NOME_DO_BOT> <REGIAO>
   ```

## Saídas

- **CSV consolidado da região:** `AAAAMMDD_REGIAO_BOT.csv` (separador `;`, decimal `,`).
- **Backup por estado em parquet:** pasta `BACKUP`, arquivos `AAAAMMDD_REGIAO_ESTADO_BOT.parquet`.
- **Capturas de tela** dos erros, na pasta configurada. Elas são apagadas quando a coleta termina com sucesso.

## Como criar um novo bot

1. Crie o arquivo `bot_<site>.py` com uma função `main_<site>`.
2. A função recebe, nesta ordem: estado, usuário, senha, endereço do site e um DataFrame vazio. Também recebe `driver`, `license_key` e `user_id` como argumentos nomeados, e cada bot lê só o que precisa.
3. Ela deve devolver três valores: o DataFrame com os produtos, o tipo de erro e a mensagem de erro.
4. O DataFrame precisa seguir o padrão de colunas do orquestrador: `Fonte`, `Site`, `EAN`, `Descrição do Produto`, `Data e hora da coleta`, `Estado`, `Concorrente`, `Estoque`, `Quantidade de estoque`, `Quantidade por pacote`, `Preço Fábrica`, `Desconto`, `ST` e `Preço Final`.
5. Para sinalizar falhas conhecidas, o bot lança as mensagens padronizadas que o orquestrador reconhece, como erro de login ou de captcha.

## Limitações

- Cada bot depende da estrutura do site de origem: se o layout mudar, é preciso ajustar o módulo daquele site.
- A planilha de acessos é um arquivo à parte, que cada pessoa monta com os próprios acessos.
- A validação de EAN cobre os casos tratados no código e não substitui a conferência com a base de produtos.

## Próximos passos

- Enviar o resultado para um banco de dados ou API (o código já tem um ponto de extensão para isso).
- Agendamento automático das execuções.
- Log estruturado das coletas e dos erros.
- Testes automatizados para as funções de validação.
