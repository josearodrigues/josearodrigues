#!/usr/bin/env python3
"""
Script para analisar linguagens nos repositórios e atualizar o README
"""

import os
import re
import requests
from collections import defaultdict
from datetime import datetime

def get_language_stats(username, token):
    """
    Busca todas as linguagens de programação dos repositórios do usuário
    """
    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json'
    }
    
    url = f'https://api.github.com/users/{username}/repos'
    params = {
        'type': 'owner',
        'per_page': 100,
        'sort': 'updated'
    }
    
    language_stats = defaultdict(int)
    page = 1
    
    while True:
        params['page'] = page
        response = requests.get(url, headers=headers, params=params)
        
        if response.status_code != 200:
            print(f"Erro ao buscar repos: {response.status_code}")
            return None
        
        repos = response.json()
        if not repos:
            break
        
        for repo in repos:
            languages_url = repo['languages_url']
            lang_response = requests.get(languages_url, headers=headers)
            
            if lang_response.status_code == 200:
                languages = lang_response.json()
                for lang, bytes_count in languages.items():
                    language_stats[lang] += bytes_count
        
        page += 1
    
    return language_stats

def calculate_percentages(language_stats):
    """
    Calcula o percentual de cada linguagem
    """
    if not language_stats:
        return []
    
    total = sum(language_stats.values())
    percentages = []
    
    for lang, bytes_count in sorted(language_stats.items(), key=lambda x: x[1], reverse=True):
        percentage = (bytes_count / total) * 100
        percentages.append((lang, percentage))
    
    return percentages

def create_progress_bar(percentage, width=20):
    """
    Cria uma barra de progresso em texto
    """
    filled = int((percentage / 100) * width)
    bar = '█' * filled + '░' * (width - filled)
    return bar

def generate_markdown(percentages):
    """
    Gera o markdown com o gráfico de linguagens
    """
    if not percentages:
        return "Nenhuma linguagem encontrada"
    
    markdown = "## 📊 Estatísticas de Linguagens\n\n"
    
    for lang, percentage in percentages[:10]:  # Top 10 linguagens
        bar = create_progress_bar(percentage)
        markdown += f"`{lang:12}` {bar} {percentage:5.1f}%\n"
    
    markdown += f"\n*Última atualização: {datetime.now().strftime('%d/%m/%Y às %H:%M:%S')}*\n"
    
    return markdown

def update_readme(readme_path, new_section):
    """
    Atualiza o README com a nova seção de estatísticas
    """
    try:
        with open(readme_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        print(f"Arquivo {readme_path} não encontrado")
        return False
    
    # Padrão para encontrar a seção de estatísticas
    pattern = r'## 📊 Estatísticas de Linguagens\n\n.*?(?=\n## |\n---|\Z)'
    
    if re.search(pattern, content, re.DOTALL):
        # Substitui a seção existente
        new_content = re.sub(pattern, new_section.rstrip() + '\n', content, flags=re.DOTALL)
    else:
        # Adiciona antes da seção de "Linguagens e Tecnologias" ou no final
        if '## 💻 Linguagens e Tecnologias' in content:
            content = content.replace('## 💻 Linguagens e Tecnologias', new_section + '\n---\n\n## 💻 Linguagens e Tecnologias')
            new_content = content
        else:
            new_content = content + '\n\n' + new_section
    
    try:
        with open(readme_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        return True
    except Exception as e:
        print(f"Erro ao escrever arquivo: {e}")
        return False

def main():
    """
    Função principal
    """
    username = os.getenv('GITHUB_REPOSITORY_OWNER', 'josearodrigues')
    token = os.getenv('GITHUB_TOKEN')
    readme_path = os.getenv('README_PATH', 'README.md')
    
    if not token:
        print("GITHUB_TOKEN não definido")
        return False
    
    print(f"Analisando repositórios de {username}...")
    
    # Busca estatísticas
    language_stats = get_language_stats(username, token)
    
    if language_stats is None:
        print("Erro ao buscar estatísticas")
        return False
    
    if not language_stats:
        print("Nenhuma linguagem encontrada")
        return False
    
    # Calcula percentuais
    percentages = calculate_percentages(language_stats)
    
    print(f"Encontradas {len(percentages)} linguagens")
    for lang, percentage in percentages[:10]:
        print(f"  {lang}: {percentage:.1f}%")
    
    # Gera markdown
    markdown = generate_markdown(percentages)
    
    # Atualiza README
    if update_readme(readme_path, markdown):
        print(f"✅ {readme_path} atualizado com sucesso!")
        return True
    else:
        print(f"❌ Erro ao atualizar {readme_path}")
        return False

if __name__ == '__main__':
    success = main()
    exit(0 if success else 1)
