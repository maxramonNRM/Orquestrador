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

ARQUIVO_USUARIOS = os.environ["COLLECT_USERS_FILE"]
PASTA_SAIDA = os.environ["COLLECT_OUTPUT_DIR"]
PASTA_CAPTURAS = os.environ["COLLECT_SCREENSHOT_DIR"]
PASTA_BASE_DOWNLOAD = os.environ["COLLECT_DOWNLOAD_DIR"]
CAMINHO_DRIVER_ALTERNATIVO = os.environ.get("COLLECT_DRIVER_PATH")

MAXIMO_TENTATIVAS = 10

# Desabilita verificação SSL para permitir atualização automática do edgedriver
os.environ["WDM_SSL_VERIFY"] = "0"

# Padrão de colunas que TODO bot deve devolver
nomes_colunas = [
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
ROTULOS_ERRO = [
    (SessionNotCreatedException, "Driver desatualizado"),
    (NoSuchElementException, "Elemento não encontrado"),
    (ElementClickInterceptedException, "Elemento interceptado"),
    (ConnectionRefusedError, "Erro de conexão"),
    (TimeoutException, "Erro de time out"),
]

# Erros lançados pelos próprios bots, identificados pela mensagem
MENSAGENS_ERRO = {
    "Login error: incorrect username or password": "Erro de login",
    "Captcha error: captcha insertion needed": "Erro de captcha",
    "Gathering error: robot gathered no rows": "Erro de coleta",
}


class ExcecaoColeta(Exception):
    pass


########################################################################
# CARGA DINÂMICA DO BOT
########################################################################

def carregar_bot(nome_bot):
    # Equivale a "from bot_<nome> import main_<nome>", mas dinâmico.
    try:
        modulo = importlib.import_module(f"bot_{nome_bot.lower()}")
        return getattr(modulo, f"main_{nome_bot.lower()}")
    except (ModuleNotFoundError, AttributeError):
        raise Exception("Bot ainda não cadastrado!")


########################################################################
# USUÁRIOS
########################################################################

def obter_info_usuarios(nome_bot, regiao):
    # Lê a base de usuários e filtra pelo bot e pela região.
    df_usuarios = pd.read_excel(ARQUIVO_USUARIOS)
    df_usuarios = df_usuarios[df_usuarios["Executar"] == "Sim"]

    df_usuarios = df_usuarios[
        (df_usuarios["Site"].str.replace(" ", "").str.upper() == nome_bot.upper())
        & (df_usuarios["Região"] == regiao)
    ]

    return df_usuarios[[
        "Usuario", "Senha", "Licenca", "Roda em tela",
        "Navegacao anonima", "IdUsuario", "Estado", "Website",
    ]]


def obter_credenciais(df_info_usuarios, estado):
    # Pega a linha de acesso de um estado.
    linha = df_info_usuarios[df_info_usuarios["Estado"] == estado].iloc[0]

    return {
        "usuario": linha["Usuario"],
        "senha": linha["Senha"],
        "com_tela": linha["Roda em tela"],
        "anonimo": linha["Navegacao anonima"],
        "caminho_site": linha["Website"],

    }


########################################################################
# NAVEGADOR
########################################################################

def criar_driver(nome_bot, com_tela, anonimo):
    opcoes = webdriver.EdgeOptions()

    if com_tela == "Não":
        opcoes.add_argument("--headless=new")

    if anonimo == "Sim":
        opcoes.add_argument("-inprivate")

    # Pasta de download própria de cada bot (alguns sites exportam arquivos)
    pasta_download = os.path.join(PASTA_BASE_DOWNLOAD, nome_bot.capitalize(), "temp")
    os.makedirs(pasta_download, exist_ok=True)

    opcoes.add_argument("--disable-extensions")
    opcoes.add_argument("--log-level=3")
    opcoes.add_argument("--disable-application-cache")
    opcoes.add_argument("--disk-cache-size=0")
    opcoes.add_experimental_option("detach", True)
    opcoes.add_experimental_option("excludeSwitches", ["enable-logging"])
    opcoes.add_experimental_option("prefs", {
        "profile.default_content_setting_values.notifications": 2,
        "profile.default_content_settings.popups": 0,
        "download.default_directory": pasta_download,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
    })

    # Tenta baixar o driver automaticamente; se falhar, usa um driver local.
    try:
        return webdriver.Edge(
            service=Service(EdgeChromiumDriverManager().install()),
            options=opcoes,
        )
    except Exception:
        if not CAMINHO_DRIVER_ALTERNATIVO:
            raise
        return webdriver.Edge(service=Service(CAMINHO_DRIVER_ALTERNATIVO), options=opcoes)


########################################################################
# PADRONIZAÇÃO DOS DADOS
########################################################################

FRASES_INDESEJADAS = [
    r"\(\s*AVISE[- ]?ME\s+QUANDO\s+CHEGAR\s*\)",
    r"\(\s*INDISPONIVEL\s*\)",
    r"\(\s*BLOQUEIO\s+POR\s+DATA\s+DE\s+VALIDADE\s*\)",
]


def padronizar_descricao(descricao):
    descricao = unidecode.unidecode(str(descricao))  # remove acentuação

    # Remove frases indesejadas em qualquer posição
    for frase in FRASES_INDESEJADAS:
        descricao = re.sub(frase, "", descricao, flags=re.IGNORECASE)

    descricao = re.sub(r"[\x00-\x1F\x7F\u2000-\u200F\u2028-\u202F\uFEFF]", "", descricao)  # caracteres de controle
    descricao = descricao.encode("latin1", errors="replace").decode("latin1")  # garante compatibilidade latin-1
    descricao = re.sub(r'[_*"!#`?]', " ", descricao)  # caracteres específicos
    descricao = re.sub(r"\s+", " ", descricao).strip()  # espaços múltiplos
    return descricao.upper()


def formatar_df_produtos(df_produtos):
    df_produtos_final = df_produtos.drop_duplicates().reset_index()[nomes_colunas]

    # Garante colunas numéricas (pd.NA vira NaN)
    for coluna in ["Preço Fábrica", "Desconto", "ST", "Preço Final"]:
        df_produtos_final[coluna] = pd.to_numeric(df_produtos_final[coluna], errors="coerce")

    preco_fabrica = df_produtos_final["Preço Fábrica"]
    preco_final = df_produtos_final["Preço Final"]

    fabrica_ok = preco_fabrica.notna() & (preco_fabrica != 0)
    final_ok = preco_final.notna() & (preco_final != 0)

    # Pelo menos um dos preços precisa ser válido; Preço Final pode ser vazio, mas não zero
    df_produtos_final = df_produtos_final[
        (fabrica_ok | final_ok) & (preco_final.isna() | (preco_final != 0))
    ].copy()

    # Descrição não pode ser vazia
    df_produtos_final = df_produtos_final[df_produtos_final["Descrição do Produto"] != ""]

    # Descrição sem acentos nem caracteres especiais
    df_produtos_final["Descrição do Produto"] = (
        df_produtos_final["Descrição do Produto"].apply(padronizar_descricao)
    )

    # EAN precisa ser numérico (o apóstrofo inicial é um artifício para o Excel)
    ean_limpo = df_produtos_final["EAN"].astype(str).str.replace("'", "", regex=False)
    df_produtos_final = df_produtos_final[ean_limpo.str.isdigit()]

    # Exclui Códigos de teste/problemáticos (sequências de 7 dígitos iguais no início ou no fim)
    padrao = (
        r"^(0{7}|1{7}|2{7}|3{7}|4{7}|5{7}|6{7}|7{7}|8{7}|9{7})|"
        r"(0{7}|1{7}|2{7}|3{7}|4{7}|5{7}|6{7}|7{7}|8{7}|9{7})$"
    )
    ean_limpo = df_produtos_final["EAN"].str.replace("'", "", regex=False)
    df_produtos_final = df_produtos_final[~ean_limpo.str.contains(padrao, regex=True)].copy()

    # Quantidade por pacote não pode ser 0
    df_produtos_final["Quantidade por pacote"] = df_produtos_final["Quantidade por pacote"].replace(0, pd.NA)

    # Arredonda colunas numéricas
    df_produtos_final["Preço Fábrica"] = df_produtos_final["Preço Fábrica"].round(2)
    df_produtos_final["Desconto"] = df_produtos_final["Desconto"].round(5)
    df_produtos_final["ST"] = df_produtos_final["ST"].round(2)
    df_produtos_final["Preço Final"] = df_produtos_final["Preço Final"].round(2)

    # Elimina duplicados mantendo o primeiro registro coletado por EAN/Concorrente/Estado
    df_produtos_final["index"] = df_produtos_final.index
    df_agrupado = (
        df_produtos_final.groupby(["EAN", "Concorrente", "Estado"])
        .agg({"index": "min"})
        .reset_index()
    )
    df_produtos_final = pd.merge(
        df_produtos_final, df_agrupado,
        on=["index"], how="inner", suffixes=("", "_2"),
    )[nomes_colunas].reset_index(drop=True)

    return df_produtos_final


########################################################################
# SAÍDA
########################################################################

def salvar_saidas(df, caminho_csv, regiao, estado, nome_bot):
    # 1. CSV consolidado da região (cada estado acrescenta linhas)
    df.to_csv(caminho_csv, sep=";", decimal=",", mode="a",
              index=False, header=False, encoding="latin1")

    # 2. Backup em parquet por estado (EAN sem o apóstrofo)
    pasta_backup = os.path.join(PASTA_SAIDA, "BACKUP")
    os.makedirs(pasta_backup, exist_ok=True)

    df_backup = df.copy()
    df_backup["EAN"] = df_backup["EAN"].str.replace("'", "", regex=False)
    nome_backup = "_".join([
        datetime.datetime.today().strftime("%Y%m%d"), regiao, estado, nome_bot,
    ]) + ".parquet"
    df_backup.to_parquet(os.path.join(pasta_backup, nome_backup),
                         engine="pyarrow", compression="gzip")

    # 3. Ponto de extensão: envie `df` para o destino que preferir (banco, API, etc.)


########################################################################
# MAIN
########################################################################

def classificar_erro(erro):
    if str(erro) in MENSAGENS_ERRO:
        return MENSAGENS_ERRO[str(erro)]
    for tipo_excecao, rotulo in ROTULOS_ERRO:
        if isinstance(erro, tipo_excecao):
            return rotulo
    return "Erro desconhecido"


def executar(nome_bot, regiao):
    principal = carregar_bot(nome_bot)

    # Embaralha a ordem dos estados para não rodar sempre na mesma sequência
    df_info_usuarios = obter_info_usuarios(nome_bot, regiao).sample(frac=1)

    print(f"######################### COLETA - {nome_bot.upper()} #########################\n\n")

    os.makedirs(PASTA_SAIDA, exist_ok=True)
    os.makedirs(PASTA_CAPTURAS, exist_ok=True)

    hora_inicio_processo = datetime.datetime.today()

    # DataFrame vazio: ponto de partida de cada bot
    df_produtos_0 = pd.DataFrame(columns=nomes_colunas)

    # CSV da região: criado só com cabeçalho e preenchido a cada estado
    caminho_csv = os.path.join(
        PASTA_SAIDA,
        "_".join([datetime.datetime.today().strftime("%Y%m%d"), regiao, nome_bot.upper()]) + ".csv",
    )
    if not os.path.exists(caminho_csv):
        df_produtos_0.to_csv(caminho_csv, sep=";", decimal=",", index=False, encoding="latin1")

    for estado in df_info_usuarios["Estado"].tolist():

        cred = obter_credenciais(df_info_usuarios, estado)
        com_tela = cred["com_tela"]

        caminho_captura = os.path.join(
            PASTA_CAPTURAS,
            "_".join([hora_inicio_processo.strftime("%Y%m%d%H%M%S"), estado, nome_bot + ".png"]),
        )

        print(f"Usuário: {cred['usuario']}, Estado: {estado}\n")

        tipo_erro, mensagem_excecao = None, None

        for tentativa in range(1, MAXIMO_TENTATIVAS + 1):
            print(f"Tentativa #{tentativa}")
            driver = None

            try:
                driver = criar_driver(nome_bot, com_tela, cred["anonimo"])
                driver.maximize_window()

                # Contrato com os bots: argumentos posicionais fixos + kwargs específicos de cada site.
                # Cada bot lê de **kwargs apenas o que precisa.
                df_produtos, tipo_erro, mensagem_excecao = principal(
                    estado,
                    cred["usuario"],
                    cred["senha"],
                    cred["caminho_site"],
                    df_produtos_0,
                    driver=driver,
                    license_key=cred["licenca"],
                    user_id=cred["id_usuario"],
                )

                df_final = formatar_df_produtos(df_produtos)

                if df_final.shape[0] == 0:
                    raise ExcecaoColeta("Gathering error: robot gathered no rows")

                salvar_saidas(df_final, caminho_csv, regiao, estado, nome_bot)

                tipo_erro, mensagem_excecao = None, None
                break

            except Exception as erro:
                tipo_erro = classificar_erro(erro)
                mensagem_excecao = str(erro)

                try:
                    # Print de tela do erro para análise futura
                    driver.save_screenshot(caminho_captura)
                except Exception as erro_captura:
                    print(f"\tErro ao capturar a tela: {erro_captura}\n")
                    com_tela = "Sim"  # se não deu para capturar, roda em tela na próxima tentativa

                print(f"{tipo_erro}: {mensagem_excecao}\n\nTentando novamente...\n")

            finally:
                if driver is not None:
                    driver.quit()

        # Remove o print se a coleta deu certo no final
        if tipo_erro is None and os.path.exists(caminho_captura):
            os.remove(caminho_captura)

        print(f"\nFim de processo: estado de {estado} (erro: {tipo_erro})\n")

    print(f"Fim de processo para todos os estados na região {regiao} do bot {nome_bot}.")


if __name__ == "__main__":
    executar(nome_bot=sys.argv[1], regiao=sys.argv[2])