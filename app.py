import logging
from datetime import datetime
from flask import Flask, request, Response
import requests
import xml.etree.ElementTree as ET
import re

app = Flask(__name__)
logging.basicConfig(level=logging.DEBUG)

OMDB_API_KEY = 'b4a46f4b'  # Substitua pela sua chave OMDb real
BRAZUCA_API_BASE = 'https://27a5b2bfe3c0-stremio-brazilian-addon.baby-beamup.club/stream/movie'

CATEGORY_MOVIE = '2000'

def size_to_bytes(size_str):
    try:
        size_str = size_str.strip().upper()
        number, unit = size_str.split()
        number = float(number)
        if unit == "GB":
            return int(number * 1024**3)
        elif unit == "MB":
            return int(number * 1024**2)
        elif unit == "KB":
            return int(number * 1024)
    except Exception as e:
        logging.warning(f"Erro ao converter tamanho: {size_str} — {e}")
    return 0

def parse_size(title):
    # Procura por padrões como "2.13 GB", "700 MB", "512 KB", etc.
    m_size = re.search(r'([\d\.]+)\s*(GB|MB|KB)', title, re.IGNORECASE)
    if m_size:
        return size_to_bytes(f"{m_size.group(1)} {m_size.group(2)}")
    return 0

def build_rss(items):
    rss = ET.Element('rss', version="2.0")
    channel = ET.SubElement(rss, 'channel')
    ET.SubElement(channel, 'title').text = "Brazuca"

    for item in items:
        itm = ET.SubElement(channel, 'item')
        ET.SubElement(itm, 'title').text = item['title']
        ET.SubElement(itm, 'link').text = item['link']

        guid = ET.SubElement(itm, 'guid', isPermaLink="false")
        guid.text = item['guid']

        ET.SubElement(itm, 'pubDate').text = item['pubDate']
        ET.SubElement(itm, 'category').text = str(item['category'])

        enclosure = ET.SubElement(itm, 'enclosure')
        enclosure.set('url', item['link'])
        enclosure.set('length', str(item.get('length', 0)))
        enclosure.set('type', 'application/x-bittorrent')

    return ET.tostring(rss, encoding='utf-8', xml_declaration=True)

def query_omdb(title):
    title_clean = re.sub(r'\s+\d{4}$', '', title)
    logging.debug(f"Consultando OMDb para título limpo: {title_clean}")
    url = f'https://www.omdbapi.com/?apikey={OMDB_API_KEY}&t={requests.utils.quote(title_clean)}'
    r = requests.get(url)
    if r.status_code != 200:
        logging.warning(f"OMDb retornou status {r.status_code}")
        return None
    data = r.json()
    if data.get('Response') == 'True':
        logging.debug(f"OMDb achou IMDB ID: {data.get('imdbID')}")
        return data.get('imdbID')
    else:
        logging.warning(f"OMDb não encontrou filme: {title_clean}")
        return None

def query_brazuca(imdbid, omdb_title=None):
    logging.debug(f"Consultando Brazuca para imdbid: {imdbid}")
    url = f"{BRAZUCA_API_BASE}/{imdbid}.json"
    r = requests.get(url)
    if r.status_code != 200:
        logging.warning(f"Brazuca retornou status {r.status_code} para imdbid {imdbid}")
        return []
    data = r.json()
    items = []
    for torrent in data.get('streams', []):
        torrent_title = torrent.get('title', 'Unknown')
        full_title = f"{omdb_title} - {torrent_title}" if omdb_title else torrent_title
        size_bytes = parse_size(torrent_title)
        item = {
            'title': full_title,
            'link': f"magnet:?xt=urn:btih:{torrent.get('infoHash', '')}&dn={requests.utils.quote(full_title)}",
            'guid': torrent.get('infoHash', ''),
            'pubDate': datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT'),
            'category': CATEGORY_MOVIE,
            'length': size_bytes
        }
        items.append(item)
    return items

@app.route('/torznab/api')
def torznab_api():
    t = request.args.get('t')
    cat = request.args.get('cat', '')
    q = request.args.get('q', None)
    imdbid = request.args.get('imdbid', None)

    logging.debug(f"Request parameters: t={t}, cat={cat}, q={q}, imdbid={imdbid}")

    if t == 'caps':
        logging.debug("Respondendo à requisição 'caps'")
        rss = ET.Element('caps')

        searching = ET.SubElement(rss, 'searching')
        ET.SubElement(searching, 'search', available="yes")
        ET.SubElement(searching, 'movie-search', available="yes")
        ET.SubElement(searching, 'movie-search', available="yes")

        categories = ET.SubElement(rss, 'categories')
        category = ET.SubElement(categories, 'category', id=CATEGORY_MOVIE, name="Movies")
        ET.SubElement(category, 'subcat', id="2010", name="HD")

        xml_caps = ET.tostring(rss, encoding='utf-8', xml_declaration=True)
        return Response(xml_caps, mimetype='application/xml')    

    if t != 'search':
        logging.warning(f"Tipo de request não suportado: {t}")
        return Response("Only 'search' requests are supported.", status=400)

    requested_categories = cat.split(',')

    if CATEGORY_MOVIE not in requested_categories:
        if not q and not imdbid and not cat:
            logging.warning("Sem parâmetros nem categoria, retornando item dummy para validação")
            items = [{
                'title': 'Dummy Movie - Test',
                'link': 'magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567',
                'guid': 'magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567',
                'pubDate': datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT'),
                'category': CATEGORY_MOVIE
            }]
            rss_feed = build_rss(items)
            return Response(rss_feed, mimetype='application/xml')
        else:
            logging.warning(f"Categoria {CATEGORY_MOVIE} não solicitada, retornando vazio")
            return Response(build_rss([]), mimetype='application/xml')

    items = []

    if imdbid:
        items = query_brazuca(imdbid, None)
        if not items:
            logging.warning(f"Nenhum item encontrado para imdbid {imdbid}")
    elif q:
        imdbid_found = query_omdb(q)
        if imdbid_found:
            omdb_title = None
            url = f'https://www.omdbapi.com/?apikey={OMDB_API_KEY}&i={imdbid_found}'
            r = requests.get(url)
            if r.status_code == 200:
                data = r.json()
                if data.get('Response') == 'True':
                    omdb_title = data.get('Title')
            items = query_brazuca(imdbid_found, omdb_title)
            if not items:
                logging.warning(f"Nenhum item encontrado no Brazuca para imdbid {imdbid_found}")
        else:
            logging.warning(f"OMDb não encontrou imdbid para a busca: {q}")
    else:
        logging.warning("Nenhum parâmetro 'q' ou 'imdbid' fornecido, retornando item dummy para categoria 2000")
        items = [{
            'title': 'Dummy Movie - Test',
            'link': 'magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567',
            'guid': 'magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567',
            'pubDate': datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT'),
            'category': CATEGORY_MOVIE
        }]

    logging.debug(f"Found {len(items)} items matching the request")

    rss_feed = build_rss(items)
    logging.debug(f"Returning RSS feed:\n{rss_feed.decode('utf-8')}")

    return Response(rss_feed, mimetype='application/xml')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5050, debug=True)
