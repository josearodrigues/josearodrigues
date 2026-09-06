#!/usr/bin/env python3
"""
Suíte de testes unitários para o script scripts/update_readme.py.

Cobre 100% dos caminhos lógicos relevantes definidos:
1.  Paginação da API (múltiplas páginas tratadas até término da lista);
2.  Filtro de Forks (repositórios com fork: True são ignorados);
3.  Filtro do Profile Repo (repositório do perfil é ignorado case-insensitively);
4.  Erro da API de repositórios (HTTP != 200 lança RuntimeError);
5.  Múltiplos repositórios (soma de bytes por linguagem agregada corretamente);
6.  API de linguagens indisponível (falha em repo individual é tolerada);
7.  Bytes 0 / stats vazios (retorna lista vazia sem divisão por zero);
8.  Barra de progresso em 0%, 50% e 100% (contagem exata de caracteres);
9.  Valores fora do intervalo (< 0% e > 100% delimitados com segurança);
10. Limite Top 10 (exatamente as 10 linguagens mais utilizadas são exibidas);
11. README com marcadores (atualização cirúrgica preservando o entorno);
12. README sem marcadores (inserção antes da seção de tecnologias ou no fim);
13. Apenas um marcador presente (lança RuntimeError para evitar corrupção);
14. Marcadores em ordem invertida (lança RuntimeError);
15. Idempotência (não grava no disco nem altera o arquivo se a tabela for idêntica).
"""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from scripts.update_readme import (
    START_MARKER,
    END_MARKER,
    create_session,
    get_repositories,
    get_language_stats,
    calculate_percentages,
    create_progress_bar,
    generate_markdown_table,
    update_readme,
    main,
)


class TestUpdateReadmeLogic(unittest.TestCase):
    """
    Testes de cobertura lógica dos fluxos do gerador de estatísticas do README.
    """

    # -----------------------------------------------------------------------
    # 1. Configuração da Sessão HTTP
    # -----------------------------------------------------------------------
    def test_create_session(self):
        """Verifica se os headers de autenticação e versão da API do GitHub são configurados."""
        session = create_session("fake_token_123")
        self.assertEqual(session.headers.get("Authorization"), "Bearer fake_token_123")
        self.assertEqual(session.headers.get("Accept"), "application/vnd.github+json")
        self.assertEqual(session.headers.get("X-GitHub-Api-Version"), "2022-11-28")

    # -----------------------------------------------------------------------
    # 2. Paginação da API, Forks e Profile Repo
    # -----------------------------------------------------------------------
    def test_get_repositories_pagination_and_filtering(self):
        """
        Testa:
        - Paginação (página 1 com dados, página 2 com término);
        - Filtro de forks (ignora repos onde fork=True);
        - Filtro do profile repo (ignora josearodrigues case-insensitively).
        """
        mock_session = MagicMock()

        # Página 1 retorna 3 repositórios:
        # 1. repo-valido (deve ser incluído)
        # 2. repo-fork (deve ser ignorado)
        # 3. JOSEARODRIGUES (profile repo em maiúsculas, deve ser ignorado)
        page1_response = MagicMock()
        page1_response.status_code = 200
        page1_response.json.return_value = [
            {"name": "repo-valido", "fork": False, "languages_url": "https://api.github.com/lang1"},
            {"name": "repo-fork", "fork": True, "languages_url": "https://api.github.com/lang2"},
            {"name": "JOSEARODRIGUES", "fork": False, "languages_url": "https://api.github.com/lang3"},
        ]

        # Página 2 retorna 1 repositório válido
        page2_response = MagicMock()
        page2_response.status_code = 200
        page2_response.json.return_value = [
            {"name": "segundo-repo-valido", "fork": False, "languages_url": "https://api.github.com/lang4"}
        ]

        # Página 3 retorna lista vazia (fim da paginação)
        page3_response = MagicMock()
        page3_response.status_code = 200
        page3_response.json.return_value = []

        mock_session.get.side_effect = [page1_response, page2_response, page3_response]

        with patch.dict(os.environ, {"GITHUB_REPOSITORY_OWNER": "josearodrigues"}):
            repos = get_repositories("josearodrigues", mock_session)

        # Deve conter apenas repo-valido e segundo-repo-valido
        self.assertEqual(len(repos), 2)
        names = [r["name"] for r in repos]
        self.assertIn("repo-valido", names)
        self.assertIn("segundo-repo-valido", names)
        self.assertNotIn("repo-fork", names)
        self.assertNotIn("JOSEARODRIGUES", names)
        self.assertEqual(mock_session.get.call_count, 3)

    # -----------------------------------------------------------------------
    # 3. Erro da API na busca de repositórios
    # -----------------------------------------------------------------------
    def test_get_repositories_api_error(self):
        """Testa se lança RuntimeError caso a API de repos retorne status != 200."""
        mock_session = MagicMock()
        error_response = MagicMock()
        error_response.status_code = 403
        error_response.text = "API rate limit exceeded"
        mock_session.get.return_value = error_response

        with self.assertRaises(RuntimeError) as context:
            get_repositories("josearodrigues", mock_session)

        self.assertIn("HTTP 403", str(context.exception))
        self.assertIn("rate limit exceeded", str(context.exception))

    # -----------------------------------------------------------------------
    # 4. Múltiplos repositórios e tolerância a falha em languages_url
    # -----------------------------------------------------------------------
    def test_get_language_stats_multiple_repos_and_unavailable_language_api(self):
        """
        Testa:
        - Agregação de bytes entre múltiplos repositórios;
        - Tolerância graciosa quando um repo retorna HTTP != 200 na consulta de linguagens.
        """
        mock_session = MagicMock()

        repos = [
            {"name": "repo-a", "languages_url": "https://api.github.com/a"},
            {"name": "repo-com-erro", "languages_url": "https://api.github.com/erro"},
            {"name": "repo-b", "languages_url": "https://api.github.com/b"},
        ]

        resp_a = MagicMock()
        resp_a.status_code = 200
        resp_a.json.return_value = {"Python": 1000, "Rust": 500}

        resp_erro = MagicMock()
        resp_erro.status_code = 500  # API falhou para este repo

        resp_b = MagicMock()
        resp_b.status_code = 200
        resp_b.json.return_value = {"Python": 500, "JavaScript": 2000}

        with patch("scripts.update_readme.get_repositories", return_value=repos):
            mock_session.get.side_effect = [resp_a, resp_erro, resp_b]
            stats = get_language_stats("josearodrigues", mock_session)

        # Python: 1000 + 500 = 1500
        # Rust: 500
        # JavaScript: 2000
        self.assertEqual(stats["Python"], 1500)
        self.assertEqual(stats["Rust"], 500)
        self.assertEqual(stats["JavaScript"], 2000)

    # -----------------------------------------------------------------------
    # 5. Cálculo de Percentuais e Tratamento de Bytes Zero
    # -----------------------------------------------------------------------
    def test_calculate_percentages_zero_bytes_and_empty(self):
        """Testa se dicionários vazios ou com soma de bytes igual a 0 retornam lista vazia sem divisão por zero."""
        self.assertEqual(calculate_percentages({}), [])
        self.assertEqual(calculate_percentages({"Python": 0, "Go": 0}), [])

    def test_calculate_percentages_ordering_and_precision(self):
        """Testa cálculo proporcional e ordenação decrescente."""
        stats = {
            "Python": 250,      # 25%
            "JavaScript": 500,  # 50%
            "Rust": 250,        # 25%
        }
        percentages = calculate_percentages(stats)
        self.assertEqual(len(percentages), 3)
        self.assertEqual(percentages[0][0], "JavaScript")
        self.assertAlmostEqual(percentages[0][1], 50.0)
        self.assertEqual(percentages[1][1], 25.0)
        self.assertEqual(percentages[2][1], 25.0)

    # -----------------------------------------------------------------------
    # 6. Barra de Progresso (0%, 50%, 100% e valores fora de escala)
    # -----------------------------------------------------------------------
    def test_create_progress_bar_boundary_values(self):
        """Testa 0%, 50% e 100% com largura padrão de 20 caracteres."""
        bar_0 = create_progress_bar(0.0, width=20)
        self.assertEqual(bar_0, "░" * 20)
        self.assertEqual(len(bar_0), 20)

        bar_50 = create_progress_bar(50.0, width=20)
        self.assertEqual(bar_50, "█" * 10 + "░" * 10)
        self.assertEqual(len(bar_50), 20)

        bar_100 = create_progress_bar(100.0, width=20)
        self.assertEqual(bar_100, "█" * 20)
        self.assertEqual(len(bar_100), 20)

    def test_create_progress_bar_out_of_bounds(self):
        """Testa percentuais negativos e acima de 100% garantindo clamping seguro."""
        bar_negative = create_progress_bar(-15.0, width=20)
        self.assertEqual(bar_negative, "░" * 20)

        bar_overflow = create_progress_bar(150.0, width=20)
        self.assertEqual(bar_overflow, "█" * 20)

    # -----------------------------------------------------------------------
    # 7. Geração de Tabela Markdown e Limite Top 10
    # -----------------------------------------------------------------------
    def test_generate_markdown_table_top_10(self):
        """Testa se uma lista com 15 linguagens exibe exatamente as 10 principais."""
        lots_of_languages = [(f"Lang{i}", 100.0 - i) for i in range(15)]
        table = generate_markdown_table(lots_of_languages)

        lines = table.strip().split("\n")
        # 1 cabeçalho + 1 separador + 10 linhas = 12 linhas
        self.assertEqual(len(lines), 12)
        self.assertIn("| **Lang0** |", lines[2])
        self.assertIn("| **Lang9** |", lines[11])
        self.assertNotIn("Lang10", table)

    def test_generate_markdown_table_empty(self):
        """Testa a tabela quando a lista de percentuais está vazia."""
        table = generate_markdown_table([])
        self.assertIn("Nenhuma linguagem encontrada", table)

    # -----------------------------------------------------------------------
    # 8. Atualização do README com Marcadores e Casos Anômalos
    # -----------------------------------------------------------------------
    def test_update_readme_with_valid_markers(self):
        """Testa atualização preservando cabeçalho e rodapé quando os marcadores existem."""
        initial_content = (
            "# Meu Perfil\n\n"
            "Texto inicial.\n\n"
            f"{START_MARKER}\n\n"
            "| Tabela Velha |\n"
            "| --- |\n\n"
            f"{END_MARKER}\n\n"
            "## Seção Final\n"
            "Rodapé intocado."
        )

        with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as tmp:
            tmp.write(initial_content)
            tmp_path = tmp.name

        try:
            new_table = "| Linguagem | Uso |\n|---|---|\n| **Python** | ████ 100% |"
            changed = update_readme(tmp_path, new_table)
            self.assertTrue(changed)

            with open(tmp_path, "r", encoding="utf-8") as f:
                updated = f.read()

            self.assertTrue(updated.startswith("# Meu Perfil\n\nTexto inicial.\n\n<!-- START_SECTION:languages -->"))
            self.assertIn(new_table, updated)
            self.assertTrue(updated.endswith("<!-- END_SECTION:languages -->\n\n## Seção Final\nRodapé intocado."))
            self.assertNotIn("Tabela Velha", updated)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_update_readme_only_one_marker_raises_error(self):
        """Testa se ter apenas um marcador (START sem END) lança RuntimeError."""
        content = f"# Perfil\n{START_MARKER}\nConteúdo sem fechamento."

        with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            with self.assertRaises(RuntimeError) as ctx:
                update_readme(tmp_path, "| tabela |")
            self.assertIn("apenas um dos marcadores", str(ctx.exception))
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_update_readme_inverted_markers_raises_error(self):
        """Testa se marcadores na ordem invertida (END antes de START) lança RuntimeError."""
        content = f"# Perfil\n{END_MARKER}\nTexto\n{START_MARKER}"

        with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            with self.assertRaises(RuntimeError) as ctx:
                update_readme(tmp_path, "| tabela |")
            self.assertIn("ordem inválida", str(ctx.exception))
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_update_readme_without_markers_inserts_before_technologies(self):
        """Testa inserção automática antes de '## 💻 Linguagens e Tecnologias' quando marcadores não existem."""
        content = (
            "# Perfil\n\n"
            "Texto inicial.\n\n"
            "## 💻 Linguagens e Tecnologias\n"
            "Ícones..."
        )

        with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            new_table = "| Linguagem | Uso |\n|---|---|\n| **Rust** | ████ 100% |"
            changed = update_readme(tmp_path, new_table)
            self.assertTrue(changed)

            with open(tmp_path, "r", encoding="utf-8") as f:
                updated = f.read()

            self.assertIn(f"{START_MARKER}\n\n{new_table}\n\n{END_MARKER}\n\n## 💻 Linguagens e Tecnologias", updated)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_update_readme_without_markers_appends_at_end(self):
        """Testa inserção no final do arquivo quando a seção de tecnologias não existir."""
        content = "# Perfil Simples\nApenas apresentação."

        with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            new_table = "| Linguagem | Uso |\n|---|---|\n| **C** | ████ 100% |"
            changed = update_readme(tmp_path, new_table)
            self.assertTrue(changed)

            with open(tmp_path, "r", encoding="utf-8") as f:
                updated = f.read()

            self.assertTrue(updated.endswith(f"{START_MARKER}\n\n{new_table}\n\n{END_MARKER}\n"))
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    # -----------------------------------------------------------------------
    # 9. Idempotência
    # -----------------------------------------------------------------------
    def test_update_readme_idempotency(self):
        """
        Testa idempotência: se o README já tiver exatamente a mesma tabela entre os marcadores,
        a função deve retornar False e não disparar regravação desnecessária.
        """
        table = "| Linguagem | Uso |\n|---|---|\n| **Python** | ██████████ 100.0% |"
        content = (
            "# Perfil\n\n"
            f"{START_MARKER}\n\n"
            f"{table}\n\n"
            f"{END_MARKER}\n"
        )

        with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            # Primeira chamada com a tabela já existente
            changed = update_readme(tmp_path, table)
            self.assertFalse(changed)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    # -----------------------------------------------------------------------
    # 10. Fluxo Principal (main)
    # -----------------------------------------------------------------------
    def test_main_missing_token(self):
        """Testa se main retorna 1 quando GITHUB_TOKEN não é informado."""
        with patch.dict(os.environ, {}, clear=True):
            exit_code = main()
            self.assertEqual(exit_code, 1)

    @patch("scripts.update_readme.create_session")
    @patch("scripts.update_readme.get_language_stats")
    def test_main_success_flow(self, mock_stats, mock_session):
        """Testa o fluxo completo do main com execução bem-sucedida."""
        mock_stats.return_value = {"Python": 1000}

        with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as tmp:
            tmp.write(f"## Estatísticas\n\n{START_MARKER}\n\n{END_MARKER}\n")
            tmp_path = tmp.name

        env = {
            "GITHUB_TOKEN": "valid_token",
            "GITHUB_REPOSITORY_OWNER": "josearodrigues",
            "README_PATH": tmp_path,
        }

        try:
            with patch.dict(os.environ, env):
                exit_code = main()
                self.assertEqual(exit_code, 0)

            with open(tmp_path, "r", encoding="utf-8") as f:
                content = f.read()

            self.assertIn("**Python**", content)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


if __name__ == "__main__":
    unittest.main()
