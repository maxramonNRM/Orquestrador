"""
Orquestrador genérico de coletas web com Selenium.

Cada "bot" (módulo bot_<nome>.py) implementa uma função main_<nome>(...) que
sabe coletar dados de UM site. Este script cuida de tudo que é comum:
credenciais, abertura do navegador, tentativas, tratamento de erros,
padronização do DataFrame e gravação dos arquivos de saída.

Uso:
    python run_collector.py <NOME_DO_BOT> <REGIAO>

Variáveis de ambiente (nenhum caminho ou credencial fica no código):
    COLLECT_USERS_FILE      planilha (.xlsx) com usuários/senhas/sites por estado
    COLLECT_OUTPUT_DIR      pasta de saída dos CSV/parquet
    COLLECT_SCREENSHOT_DIR  pasta das capturas de tela de erro
    COLLECT_DOWNLOAD_DIR    pasta base de downloads do navegador
    COLLECT_DRIVER_PATH     (opcional) msedgedriver.exe local, usado como fallback
"""

import os
import re
import sys
import importlib
import warnings
import datetime

import pandas as pd
import unidecode
from selenium.webdriver.edge.service import Service
from webdriver_manager.microsoft import EdgeChromiumDriverManager
from selenium.common.exceptions import (
    NoSuchElementException,
    ElementClickInterceptedException,
    SessionNotCreatedException,
    TimeoutException,
)

# Dica: se der erro de importação no selenium-wire, fixe `blinker==1.7.0`.
from seleniumwire import webdriver

warnings.simplefilter("ignore")

########################################################################
# CONFIGURAÇÃO
########################################################################

USERS_FILE = os.environ["COLLECT_USERS_FILE"]
OUTPUT_DIR = os.environ["COLLECT_OUTPUT_DIR"]
SCREENSHOT_DIR = os.environ["COLLECT_SCREENSHOT_DIR"]
DOWNLOAD_BASE_DIR = os.environ["COLLECT_DOWNLOAD_DIR"]
DRIVER_FALLBACK_PATH = os.environ.get("COLLECT_DRIVER_PATH")

MAX_ATTEMPTS = 10

# Desabilita verificação SSL para permitir atualização automática do edgedriver
os.environ["WDM_SSL_VERIFY"] = "0"

# Padrão de colunas que TODO bot deve devolver
col_names = [
    "Fonte",
    "Site",
    "EAN",
    "Descrição do Produto",
    "Data e hora da coleta",
    "Estado",
    "Concorrente",
    "Estoque",
    "Quantidade de estoque",
    "Quantidade por pacote",
    "Preço Fábrica",
    "Desconto",
    "ST",
    "Preço Final",
]

# Mapeia exceções conhecidas para um rótulo legível
ERROR_LABELS = [
    (SessionNotCreatedException, "Driver desatualizado"),
    (NoSuchElementException, "Elemento não encontrado"),
    (ElementClickInterceptedException, "Elemento interceptado"),
    (ConnectionRefusedError, "Erro de conexão"),
    (TimeoutException, "Erro de time out"),
]

# Erros lançados pelos próprios bots, identificados pela mensagem
ERROR_MESSAGES = {
    "Login error: incorrect username or password": "Erro de login",
    "Captcha error: captcha insertion needed": "Erro de captcha",
    "Gathering error: robot gathered no rows": "Erro de coleta",
}


class GatheringException(Exception):
    pass


########################################################################
# CARGA DINÂMICA DO BOT
########################################################################

def load_bot(player_name):
    # Equivale a "from bot_<player> import main_<player>", mas dinâmico.
    try:
        module = importlib.import_module(f"bot_{player_name.lower()}")
        return getattr(module, f"main_{player_name.lower()}")
    except (ModuleNotFoundError, AttributeError):
        raise Exception("Bot ainda não cadastrado!")


########################################################################
# USUÁRIOS
########################################################################

def get_user_info(player_name, region):
    # Lê a base de usuários e filtra pelo bot e pela região.
    df_users = pd.read_excel(USERS_FILE)
    df_users = df_users[df_users["Executar"] == "Sim"]

    df_users = df_users[
        (df_users["Site"].str.replace(" ", "").str.upper() == player_name.upper())
        & (df_users["Região"] == region)
    ]

    return df_users[[
        "Usuario", "Senha", "Licenca", "Roda em tela",
        "Navegacao anonima", "IdUsuario", "Estado", "Website",
    ]]


def get_credentials(df_user_info, state):
    # Pega a linha de acesso de um estado.
    row = df_user_info[df_user_info["Estado"] == state].iloc[0]

    return {
        "username": row["Usuario"],
        "password": row["Senha"],
        "headed": row["Roda em tela"],
        "in_private": row["Navegacao anonima"],
        "website_path": row["Website"],

    }


########################################################################
# NAVEGADOR
########################################################################

def build_driver(player_name, headed, in_private):
    options = webdriver.EdgeOptions()

    if headed == "Não":
        options.add_argument("--headless=new")

    if in_private == "Sim":
        options.add_argument("-inprivate")

    # Pasta de download própria de cada bot (alguns sites exportam arquivos)
    download_dir = os.path.join(DOWNLOAD_BASE_DIR, player_name.capitalize(), "temp")
    os.makedirs(download_dir, exist_ok=True)

    options.add_argument("--disable-extensions")
    options.add_argument("--log-level=3")
    options.add_argument("--disable-application-cache")
    options.add_argument("--disk-cache-size=0")
    options.add_experimental_option("detach", True)
    options.add_experimental_option("excludeSwitches", ["enable-logging"])
    options.add_experimental_option("prefs", {
        "profile.default_content_setting_values.notifications": 2,
        "profile.default_content_settings.popups": 0,
        "download.default_directory": download_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
    })

    # Tenta baixar o driver automaticamente; se falhar, usa um driver local.
    try:
        return webdriver.Edge(
            service=Service(EdgeChromiumDriverManager().install()),
            options=options,
        )
    except Exception:
        if not DRIVER_FALLBACK_PATH:
            raise
        return webdriver.Edge(service=Service(DRIVER_FALLBACK_PATH), options=options)


########################################################################
# PADRONIZAÇÃO DOS DADOS
########################################################################

UNWANTED_PHRASES = [
    r"\(\s*AVISE[- ]?ME\s+QUANDO\s+CHEGAR\s*\)",
    r"\(\s*INDISPONIVEL\s*\)",
    r"\(\s*BLOQUEIO\s+POR\s+DATA\s+DE\s+VALIDADE\s*\)",
]


def standardize_description(desc):
    desc = unidecode.unidecode(str(desc))  # remove acentuação

    # Remove frases indesejadas em qualquer posição
    for phrase in UNWANTED_PHRASES:
        desc = re.sub(phrase, "", desc, flags=re.IGNORECASE)

    desc = re.sub(r"[\x00-\x1F\x7F\u2000-\u200F\u2028-\u202F\uFEFF]", "", desc)  # caracteres de controle
    desc = desc.encode("latin1", errors="replace").decode("latin1")  # garante compatibilidade latin-1
    desc = re.sub(r'[_*"!#`?]', " ", desc)  # caracteres específicos
    desc = re.sub(r"\s+", " ", desc).strip()  # espaços múltiplos
    return desc.upper()


def format_df_products(df_products):
    df_products_final = df_products.drop_duplicates().reset_index()[col_names]

    # Garante colunas numéricas (pd.NA vira NaN)
    for c in ["Preço Fábrica", "Desconto", "ST", "Preço Final"]:
        df_products_final[c] = pd.to_numeric(df_products_final[c], errors="coerce")

    fab = df_products_final["Preço Fábrica"]
    fin = df_products_final["Preço Final"]

    fab_ok = fab.notna() & (fab != 0)
    fin_ok = fin.notna() & (fin != 0)

    # Pelo menos um dos preços precisa ser válido; Preço Final pode ser vazio, mas não zero
    df_products_final = df_products_final[
        (fab_ok | fin_ok) & (fin.isna() | (fin != 0))
    ].copy()

    # Descrição não pode ser vazia
    df_products_final = df_products_final[df_products_final["Descrição do Produto"] != ""]

    # Descrição sem acentos nem caracteres especiais
    df_products_final["Descrição do Produto"] = (
        df_products_final["Descrição do Produto"].apply(standardize_description)
    )

    # EAN precisa ser numérico (o apóstrofo inicial é um artifício para o Excel)
    ean_clean = df_products_final["EAN"].astype(str).str.replace("'", "", regex=False)
    df_products_final = df_products_final[ean_clean.str.isdigit()]

    # Exclui Códigos de teste/problemáticos (sequências de 7 dígitos iguais no início ou no fim)
    pattern = (
        r"^(0{7}|1{7}|2{7}|3{7}|4{7}|5{7}|6{7}|7{7}|8{7}|9{7})|"
        r"(0{7}|1{7}|2{7}|3{7}|4{7}|5{7}|6{7}|7{7}|8{7}|9{7})$"
    )
    ean_clean = df_products_final["EAN"].str.replace("'", "", regex=False)
    df_products_final = df_products_final[~ean_clean.str.contains(pattern, regex=True)].copy()

    # Quantidade por pacote não pode ser 0
    df_products_final["Quantidade por pacote"] = df_products_final["Quantidade por pacote"].replace(0, pd.NA)

    # Arredonda colunas numéricas
    df_products_final["Preço Fábrica"] = df_products_final["Preço Fábrica"].round(2)
    df_products_final["Desconto"] = df_products_final["Desconto"].round(5)
    df_products_final["ST"] = df_products_final["ST"].round(2)
    df_products_final["Preço Final"] = df_products_final["Preço Final"].round(2)

    # Elimina duplicados mantendo o primeiro registro coletado por EAN/Concorrente/Estado
    df_products_final["index"] = df_products_final.index
    df_grouped = (
        df_products_final.groupby(["EAN", "Concorrente", "Estado"])
        .agg({"index": "min"})
        .reset_index()
    )
    df_products_final = pd.merge(
        df_products_final, df_grouped,
        on=["index"], how="inner", suffixes=("", "_2"),
    )[col_names].reset_index(drop=True)

    return df_products_final


########################################################################
# SAÍDA
########################################################################

def save_outputs(df, csv_path, region, state, player_name):
    # 1. CSV consolidado da região (cada estado acrescenta linhas)
    df.to_csv(csv_path, sep=";", decimal=",", mode="a",
              index=False, header=False, encoding="latin1")

    # 2. Backup em parquet por estado (EAN sem o apóstrofo)
    backup_dir = os.path.join(OUTPUT_DIR, "BACKUP")
    os.makedirs(backup_dir, exist_ok=True)

    df_backup = df.copy()
    df_backup["EAN"] = df_backup["EAN"].str.replace("'", "", regex=False)
    backup_name = "_".join([
        datetime.datetime.today().strftime("%Y%m%d"), region, state, player_name,
    ]) + ".parquet"
    df_backup.to_parquet(os.path.join(backup_dir, backup_name),
                         engine="pyarrow", compression="gzip")

    # 3. Ponto de extensão: envie `df` para o destino que preferir (banco, API, etc.)


########################################################################
# MAIN
########################################################################

def classify_error(e):
    if str(e) in ERROR_MESSAGES:
        return ERROR_MESSAGES[str(e)]
    for exc_type, label in ERROR_LABELS:
        if isinstance(e, exc_type):
            return label
    return "Erro desconhecido"


def run(player_name, region):
    main = load_bot(player_name)

    # Embaralha a ordem dos estados para não rodar sempre na mesma sequência
    df_user_info = get_user_info(player_name, region).sample(frac=1)

    print(f"######################### COLETA - {player_name.upper()} #########################\n\n")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)

    process_begin_time = datetime.datetime.today()

    # DataFrame vazio: ponto de partida de cada bot
    df_products_0 = pd.DataFrame(columns=col_names)

    # CSV da região: criado só com cabeçalho e preenchido a cada estado
    csv_path = os.path.join(
        OUTPUT_DIR,
        "_".join([datetime.datetime.today().strftime("%Y%m%d"), region, player_name.upper()]) + ".csv",
    )
    if not os.path.exists(csv_path):
        df_products_0.to_csv(csv_path, sep=";", decimal=",", index=False, encoding="latin1")

    for state in df_user_info["Estado"].tolist():

        cred = get_credentials(df_user_info, state)
        headed = cred["headed"]

        screenshot_path = os.path.join(
            SCREENSHOT_DIR,
            "_".join([process_begin_time.strftime("%Y%m%d%H%M%S"), state, player_name + ".png"]),
        )

        print(f"Usuário: {cred['username']}, Estado: {state}\n")

        error_type, exception_message = None, None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            print(f"Tentativa #{attempt}")
            driver = None

            try:
                driver = build_driver(player_name, headed, cred["in_private"])
                driver.maximize_window()

                # Contrato com os bots: argumentos posicionais fixos + kwargs específicos de cada site.
                # Cada bot lê de **kwargs apenas o que precisa.
                df_products, error_type, exception_message = main(
                    state,
                    cred["username"],
                    cred["password"],
                    cred["website_path"],
                    df_products_0,
                    driver=driver,
                    license_key=cred["license_key"],
                    user_id=cred["user_id"],
                )

                df_final = format_df_products(df_products)

                if df_final.shape[0] == 0:
                    raise GatheringException("Gathering error: robot gathered no rows")

                save_outputs(df_final, csv_path, region, state, player_name)

                error_type, exception_message = None, None
                break

            except Exception as e:
                error_type = classify_error(e)
                exception_message = str(e)

                try:
                    # Print de tela do erro para análise futura
                    driver.save_screenshot(screenshot_path)
                except Exception as shot_error:
                    print(f"\tScreenshot error: {shot_error}\n")
                    headed = "Sim"  # se não deu para capturar, roda em tela na próxima tentativa

                print(f"{error_type}: {exception_message}\n\nTentando novamente...\n")

            finally:
                if driver is not None:
                    driver.quit()

        # Remove o print se a coleta deu certo no final
        if error_type is None and os.path.exists(screenshot_path):
            os.remove(screenshot_path)

        print(f"\nFim de processo: estado de {state} (erro: {error_type})\n")

    print(f"Fim de processo para todos os estados na região {region} do bot {player_name}.")


if __name__ == "__main__":
    run(player_name=sys.argv[1], region=sys.argv[2])
