import logging
import re
from datetime import datetime

import requests
import xml.etree.ElementTree as ET
from flask import Flask, request, Response

app = Flask(__name__)
# Configura o logging para vermos o que está acontecendo no console
logging.basicConfig(level=logging.DEBUG)

# --- CONFIGURAÇÃO ---
# Substitua pela sua chave de API real do OMDb (https://www.omdbapi.com/apikey.aspx)
OMDB_API_KEY = 'b4a46f4b'

# URL base da API do addon do Stremio que queremos usar
STREMIO_ADDON_API_BASE = 'https://27a5b2bfe3c0-stremio-brazilian-addon.baby-beamup.club/stream/movie'

# Categoria para filmes no padrão Torznab
CATEGORY_MOVIE = '2000'
# --- FIM DA CONFIGURAÇÃO ---


def size_to_bytes(size_str):
    """Converte uma string de tamanho (ex: '1.8 GB') para bytes."""
    try:
        size_str = size_str.strip().upper()
        # Usa regex para encontrar o número e a unidade
        match = re.match(r'([\d\.]+)\s*([GMK]B)', size_str)
        if not match:
            return 0
        
        number, unit = match.groups()
        number = float(number)

        if unit == "GB":
            return int(number * 1024**3)
        elif unit == "MB":
            return int(number * 1024**2)
        elif unit == "KB":
            return int(number * 1024)
    except (ValueError, AttributeError):
        return 0
    return 0

def parse_size_from_title(title):
    """
    Tenta extrair o tamanho do arquivo do título do stream.
    O formato no addon do Stremio geralmente é uma nova linha com o tamanho.
    Ex: '🔥 1080p\n Dublado\n 💾 2.35 GB'
    """
    # Regex mais genérico para encontrar o tamanho, já que o formato pode variar
    m_size = re.search(r'([\d\.]+\s*(?:GB|MB|KB))', title, re.IGNORECASE)
    if m_size:
        return size_to_bytes(m_size.group(1))
    return 0

def build_rss(items):
    """Constrói o XML do feed Torznab/RSS a partir de uma lista de itens."""
    rss = ET.Element('rss', version="2.0", attrib={"xmlns:torznab": "http://torznab.com/schemas/2015/feed"})
    channel = ET.SubElement(rss, 'channel')
    ET.SubElement(channel, 'title').text = "Stremio Brazilian Addon" # Título alterado
    ET.SubElement(channel, 'description').text = "Proxy para o addon de filmes dublados do Stremio"
    ET.SubElement(channel, 'link').text = ""
    ET.SubElement(channel, 'language').text = "pt-br"

    for item in items:
        itm = ET.SubElement(channel, 'item')
        ET.SubElement(itm, 'title').text = item['title']
        ET.SubElement(itm, 'link').text = item['link']
        ET.SubElement(itm, 'guid', isPermaLink="false").text = item['guid']
        ET.SubElement(itm, 'pubDate').text = item['pubDate']
        ET.SubElement(itm, 'category').text = str(item['category'])
        
        # Atributos específicos do Torznab
        torznab_attr = ET.SubElement(itm, 'torznab:attr', name="category", value=str(item['category']))
        torznab_attr = ET.SubElement(itm, 'torznab:attr', name="size", value=str(item.get('length', 0)))
        torznab_attr = ET.SubElement(itm, 'torznab:attr', name="seeders", value="1") # Valor Fixo
        torznab_attr = ET.SubElement(itm, 'torznab:attr', name="peers", value="1") # Valor Fixo
        torznab_attr = ET.SubElement(itm, 'torznab:attr', name="language", value="pt-br")

        enclosure = ET.SubElement(itm, 'enclosure')
        enclosure.set('url', item['link'])
        enclosure.set('length', str(item.get('length', 0)))
        enclosure.set('type', 'application/x-bittorrent')

    return ET.tostring(rss, encoding='utf-8', xml_declaration=True)

def query_omdb(title):
    """Consulta o OMDb para obter o IMDB ID de um filme a partir do título."""
    # Remove o ano e outros detalhes que o Radarr possa adicionar
    title_clean = re.sub(r'\s+\d{4}$', '', title).strip()
    logging.debug(f"Consultando OMDb para título limpo: {title_clean}")
    
    if not OMDB_API_KEY or OMDB_API_KEY == 'SUA_CHAVE_AQUI':
        logging.error("Chave da API do OMDb não foi configurada.")
        return None

    url = f'https://www.omdbapi.com/?apikey={OMDB_API_KEY}&t={requests.utils.quote(title_clean)}'
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        if data.get('Response') == 'True' and 'imdbID' in data:
            logging.debug(f"OMDb achou IMDB ID: {data.get('imdbID')}")
            return data.get('imdbID')
        else:
            logging.warning(f"OMDb não encontrou filme: {title_clean} - Resposta: {data.get('Error')}")
            return None
    except requests.exceptions.RequestException as e:
        logging.error(f"Erro ao consultar OMDb: {e}")
        return None

def query_stremio_addon(imdbid):
    """Consulta o addon do Stremio para obter os streams de um filme a partir do IMDB ID."""
    logging.debug(f"Consultando Stremio Addon para imdbid: {imdbid}")
    url = f"{STREMIO_ADDON_API_BASE}/{imdbid}.json"
    try:
        r = requests.get(url, timeout=10)
        # O addon pode retornar 404 se não tiver o filme, o que é normal.
        if r.status_code != 200:
            logging.warning(f"Stremio Addon retornou status {r.status_code} para imdbid {imdbid}")
            return []
        
        data = r.json()
        items = []
        for stream in data.get('streams', []):
            title = stream.get('title', 'Título Desconhecido').replace('\n', ' ')
            info_hash = stream.get('infoHash', '')
            
            if not info_hash:
                continue

            size_bytes = parse_size_from_title(stream.get('title', ''))
            
            item = {
                'title': title,
                'link': f"magnet:?xt=urn:btih:{info_hash}&dn={requests.utils.quote(title)}",
                'guid': info_hash,
                'pubDate': datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT'),
                'category': CATEGORY_MOVIE,
                'length': size_bytes
            }
            items.append(item)
        return items
    except requests.exceptions.RequestException as e:
        logging.error(f"Erro ao consultar Stremio Addon: {e}")
        return []


@app.route('/torznab/api')
def torznab_api():
    """Rota principal que responde às requisições do Prowlarr/Radarr."""
    t = request.args.get('t')
    q = request.args.get('q')
    imdbid = request.args.get('imdbid')
    
    logging.debug(f"Request recebida: t={t}, q={q}, imdbid={imdbid}")

    if t == 'caps':
        logging.debug("Respondendo à requisição 'caps'")
        caps_xml = f"""<caps>
            <server version="1.1" title="Stremio BR Addon" strapline="Proxy para addon Stremio" email="proxy@localhost.com" url="http://localhost" image="https://i.imgur.com/V63t2n0.png"/>
            <limits max="100" default="50"/>
            <searching>
                <search available="yes" supportedParams="q,imdbid"/>
                <tv-search available="no" supportedParams="q,tvdbid,tvmazeid,imdbid,season,ep"/>
                <movie-search available="yes" supportedParams="q,imdbid"/>
                <audio-search available="no"/>
            </searching>
            <categories>
                <category id="{CATEGORY_MOVIE}" name="Movies">
                    <subcat id="2040" name="Movies HD"/>
                    <subcat id="2050" name="Movies UHD"/>
                </category>
            </categories>
        </caps>"""
        return Response(caps_xml, mimetype='application/xml')

    if t == 'search':
        items = []
        search_imdbid = imdbid
        
        # Se a busca for por texto (q), primeiro tentamos encontrar o imdbid no OMDb
        if q and not imdbid:
            search_imdbid = query_omdb(q)
        
        # Se temos um imdbid (seja da busca ou direto do request), consultamos o addon
        if search_imdbid:
            items = query_stremio_addon(search_imdbid)
            if not items:
                logging.warning(f"Nenhum item encontrado no Stremio Addon para imdbid {search_imdbid}")
        else:
            logging.warning(f"Nenhum imdbid encontrado para a busca: q={q}, imdbid={imdbid}")
            
        rss_feed = build_rss(items)
        logging.debug(f"Retornando {len(items)} itens no feed RSS.")
        return Response(rss_feed, mimetype='application/xml')

    # Se 't' não for 'caps' ou 'search', retorna um erro ou um feed vazio.
    logging.warning(f"Tipo de requisição não suportado: {t}")
    return Response(build_rss([]), mimetype='application/xml')

if __name__ == '__main__':
    # Para rodar localmente, use 0.0.0.0. Para produção, considere usar um servidor WSGI como Gunicorn.
    app.run(host='0.0.0.0', port=5000, debug=False)
