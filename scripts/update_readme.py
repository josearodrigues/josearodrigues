#!/usr/bin/env python3
"""
Atualiza automaticamente as estatísticas de linguagens do Profile README.

O script:
- Consulta os repositórios públicos pertencentes ao usuário no GitHub;
- Ignora forks e o próprio repositório do perfil;
- Consulta as linguagens utilizadas em cada repositório;
- Soma os bytes por linguagem;
- Calcula os percentuais;
- Gera uma tabela Markdown com as 10 principais linguagens;
- Atualiza somente o conteúdo delimitado pelos marcadores:

    <!-- START_SECTION:languages -->
    <!-- END_SECTION:languages -->

O restante do README permanece inalterado.

Variáveis de ambiente:
    GITHUB_TOKEN             Token fornecido pelo GitHub Actions.
    GITHUB_REPOSITORY_OWNER  Usuário proprietário do repositório (default: josearodrigues).
    README_PATH              Caminho do README (default: README.md).
"""

import os
import sys
from collections import defaultdict

import requests


# ---------------------------------------------------------------------------
# Configurações
# ---------------------------------------------------------------------------

GITHUB_API_URL = "https://api.github.com"

START_MARKER = "<!-- START_SECTION:languages -->"
END_MARKER = "<!-- END_SECTION:languages -->"

MAX_LANGUAGES = 10
PROGRESS_BAR_WIDTH = 20

# Repositório do Profile README (normalmente possui o mesmo nome do usuário/proprietário).
PROFILE_REPOSITORY = os.getenv("GITHUB_REPOSITORY_OWNER", "josearodrigues")

# Timeout para requisições HTTP (em segundos).
REQUEST_TIMEOUT = 30


# ---------------------------------------------------------------------------
# GitHub API
# ---------------------------------------------------------------------------

def create_session(token):
    """
    Cria uma sessão HTTP configurada para a API do GitHub.
    """
    session = requests.Session()

    session.headers.update(
        {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    )

    return session


def get_repositories(username, session):
    """
    Retorna todos os repositórios públicos pertencentes ao usuário.

    São ignorados:
    - forks;
    - o próprio repositório do Profile README.

    A paginação é tratada automaticamente.
    """
    repositories = []
    page = 1

    while True:
        url = f"{GITHUB_API_URL}/users/{username}/repos"

        params = {
            "type": "owner",
            "visibility": "public",
            "per_page": 100,
            "page": page,
            "sort": "updated",
        }

        response = session.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"Erro ao buscar repositórios: "
                f"HTTP {response.status_code} - {response.text}"
            )

        repos = response.json()

        if not repos:
            break

        for repo in repos:
            # Ignora o próprio repositório do Profile README (case-insensitive)
            if repo.get("name", "").lower() == PROFILE_REPOSITORY.lower():
                continue

            # Ignora forks para refletir apenas código próprio
            if repo.get("fork", False):
                continue

            repositories.append(repo)

        page += 1

    return repositories


def get_language_stats(username, session):
    """
    Consulta as linguagens de todos os repositórios públicos do usuário.

    Retorna:
        defaultdict(int): bytes totais por linguagem.
    """
    repositories = get_repositories(username, session)
    language_stats = defaultdict(int)

    print(f"Repositórios considerados: {len(repositories)}")

    for repo in repositories:
        repository_name = repo["name"]
        languages_url = repo["languages_url"]

        response = session.get(
            languages_url,
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code != 200:
            print(
                f"⚠️ Não foi possível obter linguagens de "
                f"{repository_name}: HTTP {response.status_code}"
            )
            continue

        languages = response.json()

        for language, bytes_count in languages.items():
            language_stats[language] += bytes_count

    return language_stats


# ---------------------------------------------------------------------------
# Cálculos
# ---------------------------------------------------------------------------

def calculate_percentages(language_stats):
    """
    Calcula o percentual de cada linguagem.

    Retorna uma lista ordenada:
        [(linguagem, percentual), ...]
    """
    if not language_stats:
        return []

    total_bytes = sum(language_stats.values())

    if total_bytes == 0:
        return []

    percentages = [
        (language, (bytes_count / total_bytes) * 100)
        for language, bytes_count in language_stats.items()
    ]

    percentages.sort(key=lambda item: item[1], reverse=True)

    return percentages


def create_progress_bar(percentage, width=PROGRESS_BAR_WIDTH):
    """
    Cria uma barra de progresso textual de tamanho fixo.

    Exemplo:
        50% -> ██████████░░░░░░░░░░
    """
    percentage = max(0.0, min(100.0, percentage))
    filled = round((percentage / 100) * width)

    # Garante que o resultado permaneça dentro dos limites da barra.
    filled = max(0, min(width, filled))
    empty = width - filled

    return "█" * filled + "░" * empty


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

def generate_markdown_table(percentages):
    """
    Gera a tabela Markdown mantendo o formato visual atual do README.

    Exemplo:

    | Linguagem | Uso |
    |-----------|-----|
    | **JavaScript** | ██████░░░░░░░░░░░░ 32.5% |
    """
    if not percentages:
        return (
            "| Linguagem | Uso |\n"
            "|-----------|-----|\n"
            "| **Nenhuma linguagem encontrada** | - |"
        )

    lines = [
        "| Linguagem | Uso |",
        "|-----------|-----|",
    ]

    for language, percentage in percentages[:MAX_LANGUAGES]:
        bar = create_progress_bar(percentage)

        lines.append(
            f"| **{language}** | {bar} {percentage:.1f}% |"
        )

    return "\n".join(lines)


def update_readme(readme_path, new_table):
    """
    Atualiza somente o conteúdo entre os marcadores do README.

    Se os marcadores existirem:
        preserva todo o conteúdo externo a eles.

    Se os marcadores não existirem:
        cria a seção na posição apropriada, antes de
        '## 💻 Linguagens e Tecnologias', quando disponível.

    Retorna:
        True  se o arquivo foi alterado;
        False se não houve alteração.
    """
    if not os.path.exists(readme_path):
        raise FileNotFoundError(
            f"Arquivo {readme_path} não encontrado."
        )

    with open(readme_path, "r", encoding="utf-8") as file:
        content = file.read()

    # ---------------------------------------------------------------
    # Caso 1: marcadores já existem.
    # ---------------------------------------------------------------
    start_index = content.find(START_MARKER)
    end_index = content.find(END_MARKER)

    if start_index != -1 or end_index != -1:

        # Se somente um dos marcadores existir, é uma situação inconsistente
        if start_index == -1 or end_index == -1:
            raise RuntimeError(
                "README contém apenas um dos marcadores de seção. "
                "Nenhuma alteração foi realizada."
            )

        if end_index < start_index:
            raise RuntimeError(
                "Marcadores do README estão em ordem inválida. "
                "Nenhuma alteração foi realizada."
            )

        content_before = content[: start_index + len(START_MARKER)]
        content_after = content[end_index:]

        new_content = (
            f"{content_before}\n\n"
            f"{new_table}\n\n"
            f"{content_after}"
        )

    # ---------------------------------------------------------------
    # Caso 2: marcadores ainda não existem.
    # ---------------------------------------------------------------
    else:
        section = (
            f"{START_MARKER}\n\n"
            f"{new_table}\n\n"
            f"{END_MARKER}"
        )

        technologies_heading = "## 💻 Linguagens e Tecnologias"

        if technologies_heading in content:
            new_content = content.replace(
                technologies_heading,
                f"{section}\n\n{technologies_heading}",
                1,
            )
        else:
            separator = "\n\n"
            if not content.endswith("\n"):
                separator = "\n\n"

            new_content = (
                content.rstrip()
                + separator
                + section
                + "\n"
            )

    # ---------------------------------------------------------------
    # Evita reescrita desnecessária (Idempotência).
    # ---------------------------------------------------------------
    if new_content == content:
        print("ℹ️ Nenhuma alteração necessária no README.")
        return False

    with open(readme_path, "w", encoding="utf-8") as file:
        file.write(new_content)

    return True


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------

def main():
    """
    Executa o processo completo de atualização.
    """
    username = os.getenv(
        "GITHUB_REPOSITORY_OWNER",
        "josearodrigues",
    )

    token = os.getenv("GITHUB_TOKEN")

    readme_path = os.getenv(
        "README_PATH",
        "README.md",
    )

    if not token:
        print(
            "❌ GITHUB_TOKEN não definido.",
            file=sys.stderr,
        )
        return 1

    print(f"🔎 Analisando repositórios públicos de {username}...")

    try:
        session = create_session(token)

        language_stats = get_language_stats(
            username,
            session,
        )

        if not language_stats:
            print(
                "❌ Nenhuma linguagem encontrada.",
                file=sys.stderr,
            )
            return 1

        percentages = calculate_percentages(language_stats)

        if not percentages:
            print(
                "❌ Não foi possível calcular os percentuais.",
                file=sys.stderr,
            )
            return 1

        print(f"📊 Linguagens encontradas: {len(percentages)}")

        for language, percentage in percentages[:MAX_LANGUAGES]:
            print(f"   {language}: {percentage:.1f}%")

        table = generate_markdown_table(percentages)

        changed = update_readme(
            readme_path,
            table,
        )

        if changed:
            print(f"✅ {readme_path} atualizado com sucesso!")
        else:
            print("✅ README já está atualizado.")

        return 0

    except requests.RequestException as error:
        print(
            f"❌ Erro de comunicação com a API do GitHub: {error}",
            file=sys.stderr,
        )
        return 1

    except (RuntimeError, FileNotFoundError) as error:
        print(
            f"❌ {error}",
            file=sys.stderr,
        )
        return 1

    except Exception as error:
        print(
            f"❌ Erro inesperado: {error}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())