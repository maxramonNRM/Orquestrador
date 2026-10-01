"""
Bot modelo. Para criar uma nova coleta, copie este arquivo para bot_<nome>.py
e renomeie a função para main_<nome>. O orquestrador (run_collector.py) o
encontra sozinho pelo nome passado na linha de comando.

Contrato:
    - Recebe: state, username, password, website_path, df_products_0 e **kwargs
      (driver, license_key, user_id, ...). Use só o que o site precisar.
    - Devolve: (DataFrame com as colunas padrão, error_type, exception_message)
"""

import datetime
import pandas as pd

col_names = [
    "Fonte", "Site", "EAN", "Descrição do Produto", "Data e hora da coleta",
    "Estado", "Concorrente", "Estoque", "Quantidade de estoque",
    "Quantidade por pacote", "Preço Fábrica", "Desconto", "ST", "Preço Final",
]


def main_example(state, username, password, website_path, df_products_0, **kwargs):

    driver = kwargs["driver"]

    error_type = None
    exception_message = None

    driver.get(website_path)

    # 1. Login com username/password
    # 2. Navegação até a página (ou exportação) dos produtos
    # 3. Leitura dos dados e montagem do DataFrame

    data_hora = datetime.datetime.today().strftime("%Y-%m-%d %H:%M:%S")

    df_site = pd.DataFrame(columns=col_names)  # substitua pelos dados coletados
    df_site["Data e hora da coleta"] = data_hora
    df_site["Estado"] = state

    df_products_0 = pd.concat([df_products_0, df_site])

    return df_products_0, error_type, exception_message
